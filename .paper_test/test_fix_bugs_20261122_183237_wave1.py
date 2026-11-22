#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance checks for the 2026-11-22 fix-bugs wave 1 (run 20261122-183237).

One check per confirmed candidate whose surface is testable without a full
round. Each check FAILS on the pre-fix tree and passes after the smallest
patch recorded in the stage ledger.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402
import paper_docx_format as df      # noqa: E402

FAILS: list[str] = []
TMPDIRS: list[Path] = []


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def _stat(median=5.0, mean=None, iqr=0.0, digest="d", complete=True, n=2):
    return {"n": n, "median": median, "mean": mean if mean is not None else median,
            "iqr": iqr, "complete": complete, "vs_original_complete": True,
            "anti_regression_ok": True, "digest": digest}


def _census(fatal_own=0):
    tiers = {t: {"severities": {s: {"own": 0, "peer": 0} for s in pp.SEVERITIES}}
             for t in pp.BASIS_TIERS}
    tiers["correctness"]["severities"]["fatal"]["own"] = fatal_own
    return {"tiers": tiers}


# ---------------------------------------------------------------- ranking
def test_ranking() -> None:
    print("\n== ranking: F004/F028/F030 ==")
    r = pp.derive_ranking({"BASE": _stat(5.0, complete=False, digest="b"),
                           "w1": _stat(5.0, digest="w")},
                          ["w1"], "BASE", {}, 1, 1)
    check("F185 an incomplete base panel is retained when the leader ties it",
          r["champion"] == "a1", r["champion"])
    r = pp.derive_ranking({"a1": _stat("5"), "w1": _stat("5")}, ["w1"], "a1", {}, 1, 1)
    check("F028 a non-numeric median is ineligible, not a crash",
          r["champion"] == "a1" and any("missing panel statistic" in t for t in r["trace"]),
          r["champion"])
    r = pp.derive_ranking({"a1": _stat(2.0, digest="b"), "w1": _stat(5.0, digest="w")},
                          ["w1"], "a1", {"a1": _census(3), "w1": {}}, 1, 1)
    check("F030 a present-but-empty census row is missing evidence",
          r["champion"] == "a1"
          and next(t for t in r["ranking"] if t["id"] == "w1")["defect_prefix_census"] is None,
          [(t["id"], t.get("defect_prefix_census")) for t in r["ranking"]])


# ---------------------------------------------------------------- coverage gates
def test_coverage_gates() -> None:
    print("\n== coverage/disposition gates ==")
    for text in ("0 findings; the sweep was skipped", "0 findings; skipped",
                 "3 findings; the sweep was skipped", "0 findings; we could not check anything",
                 "0 findings; the work was not done", "0 findings; nobody looked at it",
                 "0 findings; I never looked", "0 findings; the check did not happen"):
        check(f"F001 audit count tail refused: {text!r}",
              pp._audit_disposition_ok(text) is False)
    check("F001 an item-level inability still leaves the count standing",
          pp._audit_disposition_ok("3 findings; unable to check one quoted line") is True)
    check("F082 one-letter prose-`unable` object is filler",
          pp._audit_disposition_ok("unable to check x") is False)
    for text in ("clean -- basis: skipped", "clean -- basis: not attempted",
                 "clean -- basis: deferred", "0 findings; see above",
                 "clean -- basis: pdftoppm not installed",
                 "clean -- basis: LibreOffice is unavailable"):
        check(f"F005 coverage disposition refused: {text!r}",
              pp._coverage_disposition_ok(text) is False)
    check("F005 a named basis is still accepted",
          pp._coverage_disposition_ok("clean -- basis: artifacts/M1_acronyms.md") is True)
    for text in ("OK — verified", "OK — reviewed", "OK — examined",
                 "OK — it was checked", "OK — not checked", "OK — unable to verify"):
        check(f"F105/F034 disposition refused: {text!r}",
              pp._is_recorded_reason(text) is False)
    check("F105 a disposition naming the artifact is accepted",
          pp._is_recorded_reason("OK — verified against base/main.md line 12") is True)


def test_audit_helpers() -> None:
    print("\n== audit artifact helpers: F027/F040/F043/F059/F069/F077/F082/F091/F101/F132/F133/F134 ==")
    frozen = ["F-1"]
    audit = {"round": 999,
             "dispositions": [{"id": "F-1", "verdict": "drop",
                               "reason": "the quoted sentence is absent from base/main.md",
                               "evidence": "base/main.md:12"}],
             "adds": [], "counts": {"confirmed": 99, "dropped": 0, "added": 7},
             "notes": ""}
    probs = pp.audit_artifact_problems(audit, frozen, expected_round=1)
    check("F027 a short `path:line` drop evidence is accepted",
          not any("EVIDENCE" in p for p in probs), probs)
    check("F059 a contradictory `counts`/round is rejected",
          any("counts.confirmed" in p for p in probs)
          and any("999" in p and "round" in p for p in probs), probs)
    check("F077 a null label falls back to the verdict alias",
          pp._defect_audit_row_label({"label": None, "verdict": "TP",
                                      "reason": "checked line 42 twice"})[0] == "TP")
    check("F132 an anonymous pointer is not an audit basis",
          pp._defect_audit_reason_ok("see above") is False)
    check("F040 `unknown -- counterpart undecidable` is a disposition",
          bool(pp.JUDGE_DISPOSITION_RE.search(
              "unknown -- counterpart undecidable: side b unreadable")))
    check("F069 a padded J id normalises to the frozen spelling",
          pp._frozen_check_id("J04") == "J4" and pp._frozen_check_id("M019") == "M19")
    check("F043 a one-letter named gap is refused",
          bool(pp.concern_coverage_problems(
              {"coverage": [{"check": "scope", "detail": "gap: x"}]}, False)))
    check("F134 a dedicated `gap` field is a named gap",
          pp.concern_coverage_problems(
              {"coverage": [{"check": "scope", "gap": "all content/scientific classes"}]},
              False) == [])
    check("F091 a decision after the id in the same cell reconciles",
          pp.discovery_ledger_missing("| X-001 PORTED | changed |", ["X-001"]) == []
          and pp.discovery_ledger_missing("X-001 was PORTED to the base", ["X-001"]) == [])
    check("F091 a negated decision still does not reconcile",
          pp.discovery_ledger_missing("| X-001 | NOT PORTED |", ["X-001"]) == ["X-001"])
    # F101/F037/F133/F134 need a small filesystem fixture.
    sb = scratch("fb1837_jf_")
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    (sb / "guided_review" / "artifacts" / "JF_concerns.md").write_text(
        "| id |\n|---|\n", encoding="utf-8")
    (sb / "guided_review" / "findings.json").write_text(json.dumps({
        "findings": [{"id": "JF-1", "check": "JF", "concern": "R1-1",
                      "evidence": "a totally invented quotation",
                      "location": "main.md:1", "status": "resolvable",
                      "severity": "Major", "category": 0}],
        "coverage": [{"check": "scope", "gap": "style and figure quality"}]}),
        encoding="utf-8")
    errs, _w, _c = pp.concerns_finding_list_problems(
        sb, {"concerns": [{"id": "R1-1", "disposition": "to-fix",
                           "quote": "The assay was performed at room temperature."}]})
    check("F037 invented JF evidence is refused",
          any("verbatim reviewer quote" in e for e in errs), errs[:2])
    _errs, _w, _c = pp.concerns_finding_list_problems(
        sb, {"concerns": [{"id": "R1-1", "disposition": "to-fix",
                           "quote": "The assay was performed at room temperature."}]})
    check("F134 named gap via `gap` field passes the concerns gate",
          not any("no coverage row" in e for e in _errs), _errs[:2])
    comp = {"opponent_label": "x", "score": 0, "basis": "none", "resolved": [],
            "introduced": [{"tier": "writing", "severity": "minor", "check": "M20",
                            "evidence": " ".join(["w"] * 30)}]}
    check("F133 over-long judge evidence is an error under the strict contract",
          any("30 words" in e for e in pp.judge_basis_problems(comp, "c", strict=True)[0]))


# ---------------------------------------------------------------- DOCX helpers
def test_docx_helpers() -> None:
    print("\n== DOCX helpers: F007/F010/F036/F051/F056/F058/F060/F092 ==")
    out, applied = df.rewrite_text_spans(
        '<w:p><w:r><w:t>abc</w:t><w:br/></w:r></w:p >', [(4, 4, "X")])
    check("F007 a trailing insertion lands before a whitespace-closed paragraph",
          "</w:r></w:p >" in out and out.index("X") < out.index("</w:p >"), out)
    bold = df._bold_label_runs(
        '<w:p><w:r><w:rPr w:rsidR="00A1"><w:i/></w:rPr >'
        '<w:t>* Correspondence: Jane Doe</w:t></w:r></w:p>')
    _runs = re.findall(r"<w:r\b[\s\S]*?</w:r\s*>", bold)
    check("F010 each run keeps at most ONE live rPr after bolding",
          bool(_runs) and all(r.count("<w:rPr") <= 1 for r in _runs)
          and "<w:b/>" in bold, bold)
    rows = df.number_format_rows(["We processed 1,000 samples and 2500 cells."])
    check("F036 a plain 4-digit quantity participates in FMT-T9h",
          any(r.get("rule") == "FMT-T9h" for r in rows), rows)
    ppr = df._insert_ppr_extra('<w:pPr><w:jc w:val="left"/></w:pPr >',
                               '<w:spacing w:before="240"/>')
    check("F051 template pPr children land before a whitespace-closed pPr",
          "<w:spacing" in ppr and ppr.index("<w:spacing") < ppr.index("</w:pPr >"), ppr)
    check("F056 a zero-length insertion at a replacement start is kept",
          df.apply_edits("0123456789", [(5, 10, "REPL"), (5, 5, "INS")]) == "01234INSREPL")
    check("F058 attr() decodes an entity-encoded style id",
          df.attr('<w:pStyle w:val="A&amp;B"/>', "val") == "A&B")
    check("F060 elem() finds a whitespace-closed paired empty element",
          df.elem("<w:rPr><w:b></w:b ></w:rPr>", "b") == "<w:b></w:b >")
    parts = {"word/settings.xml": (
        '<?xml version="1.0"?><w:settings xmlns:w="http://x"><w:zoom/></w:settings >'
    ).encode()}
    changed = df._with_even_odd_headers(parts)
    check("F092 even/odd is enabled on a whitespace-closed settings part",
          changed and b"<w:evenAndOddHeaders/>" in parts["word/settings.xml"])


# ---------------------------------------------------------------- text/tracking
def test_text_tracking() -> None:
    print("\n== text/tracking: F047/F118/F137/F145/F147 ==")
    sb = scratch("fb1837_sess_")
    log = sb / "_agent.log"
    head = b'{"type":"session","sessionId":"session-0123abcd-4567-89ef-0123-456789abcdef"}\n'
    with open(log, "wb") as fh:
        fh.write(head)
        fh.write(b"x" * (17 * 1024 * 1024))
    class Ctx:
        def sandbox_of(self, rec):
            return sb
    check("F047 a dsh sessionId at the head survives a >16 MiB transcript",
          pp.capture_agent_session_id(
              Ctx(), {"id": "r1"}) == "session-0123abcd-4567-89ef-0123-456789abcdef")
    link = scratch("fb1837_dir_") / "link"
    outside = scratch("fb1837_out_")
    (outside / "f.txt").write_bytes(b"12345")
    link.symlink_to(outside)
    check("F118 dir_size does not follow a symlinked root", pp.dir_size(link) == 0,
          pp.dir_size(link))
    p10 = (ROOT / "paper_pipeline_parts" / "p10_reports.py").read_text(encoding="utf-8")
    check("F137 member_mean is written unrounded",
          'out["member_mean"] = (st["mean"]' in p10
          and 'round(float(st["mean"]), 6)' not in p10)
    check("F145/F147 an absolute manifest path is not contained",
          pp.contained_under_or_none(ROOT, "/etc/passwd") is None)
    check("F019 the pipeline root itself is not a contained descendant",
          pp.contained_under_or_none(ROOT, ".") is None)
    # F023: a run sandbox must be a STRICT descendant of runs/.
    root = scratch("fb1837_sb_")
    (root / "runs").mkdir()
    (root / "non_revised").mkdir()

    class SbCtx:
        pass

    sctx = SbCtx()
    sctx.root = root
    sctx.runs_dir = root / "runs"
    sctx.pristine = root / "non_revised"
    sctx.pins_dir = root / "pinned"
    (root / "pinned").mkdir()
    sctx.state_path = root / "state.json"
    refused = []
    for value in (".", "runs/../non_revised", "non_revised"):
        try:
            pp.Ctx.sandbox_of(sctx, {"id": "r1_x", "sandbox": value})
            refused.append(value)
        except SystemExit:
            pass
    check("F023 '.'/the pristine tree are not accepted as run sandboxes",
          refused == [], refused)




def test_docx_front_and_lists() -> None:
    print("\n== DOCX front matter/lists/rows: F006/F008/F009/F012/F050/F052/F053 ==")
    check("F006 a spaced single-quoted PartName is found",
          df._ct_has_partname(
              '<Types><Override PartName = "/word/header_x.xml" ContentType="x"/></Types>',
              "/word/header_x.xml"))
    check("F053 a spaced PartName is found for settings",
          df._ct_has_partname(
              '<Types><Override PartName = "/word/settings.xml" ContentType="x"/></Types>',
              "/word/settings.xml"))
    doc = ('<w:document xmlns:w="http://w" xmlns:r = "http://r"><w:body><w:p/>'
           '<w:sectPr><w:headerReference w:type="default" r:id="rId9"/></w:sectPr>'
           '</w:body></w:document>')
    out, _changed = df._apply_front_refs(doc, {"header_default_rid": "rId1",
                                              "header_first_rid": "rId2"})
    check("F008 a legal `xmlns:r =` declaration is not duplicated",
          out.count("xmlns:r") == 1, out[:200])
    check("F050 a paired-empty headerReference is replaced, not duplicated",
          "rId9" not in out and out.count('w:type="default"') == 1, out[:300])
    doc2 = ('<w:document xmlns:w="http://w"><w:body>'
            '<!-- <w:sectPr><w:headerReference w:type="default" r:id="rId9"/></w:sectPr> -->'
            '<w:p/><w:sectPr><w:headerReference w:type="default" r:id="rId8"/></w:sectPr>'
            '</w:body></w:document>')
    out2, _c = df._apply_front_refs(doc2, {"header_default_rid": "rId1"})
    check("F009 front refs are written into the LIVE section, not the comment",
          out2.count("rId1") == 1 and out2.index("-->") < out2.index("rId1"),
          out2[:400])
    para = ('<w:p><w:pPr><!-- <w:spacing w:before="111"/> -->'
            '<w:spacing w:before="222"/></w:pPr><w:r/></w:p>')
    span = df._para_child_span(para, "spacing")
    check("F012 the live property span wins over a commented copy",
          span is not None and para[span[0]:span[1]] == '<w:spacing w:before="222"/>',
          (span, para[span[0]:span[1]] if span else None))
    numbering = '<w:numbering><w:num w:numId="1"/></w:numbering >'
    reordered = df._reorder_numbering_groups(
        numbering, "", '<w:abstractNum w:abstractNumId="9"/>', "")
    check("F052 carried abstractNum is spliced before a whitespace-closed numbering",
          '<w:abstractNum w:abstractNumId="9"/>' in reordered, reordered)
    parts = {"word/document.xml": (
        b'<w:document xmlns:w="http://w"><w:body><w:p><w:pPr><w:numPr>'
        b'<w:numId w:val="9"/></w:numPr></w:pPr></w:p></w:body></w:document>'),
        "word/numbering.xml": (b'<w:numbering xmlns:w="http://w">'
                               b'<w:num w:numId="1"/></w:numbering >')}
    carried = df._merge_source_lists(
        parts,
        '<w:numbering xmlns:w="http://w"><w:abstractNum w:abstractNumId="9">'
        '<w:lvl w:ilvl="0"/></w:abstractNum><w:num w:numId="9">'
        '<w:abstractNumId w:val="9"/></w:num></w:numbering>',
        re.compile(r"word/document\.xml"))
    check("F052 source list definitions are carried on a whitespace-closed template",
          bool(carried), carried)
    p03 = (ROOT / "paper_docx_format_parts" / "p03_report_cli.py").read_text(encoding="utf-8")
    check("F013 the title-page pass reads the masked document",
          "SECT_READ_RE.finditer(_mask_noncontent(xml))" in p03)
    check("F048 the style carry-over reads w:styleId through attr_of",
          'attr_of(om.group(0), "w:styleId")' in p03)
    check("F093 hyperlink spans tolerate a whitespace close",
          p03.count("</w:hyperlink\\s*>") >= 2)
    check("F011 a package-rooted media target is not prefixed twice",
          'if _tgt.startswith("word/")' in (
              ROOT / "paper_docx_format_parts" / "p02_layout_edit.py").read_text(
                  encoding="utf-8"))


def test_judge_discovery_shape() -> None:
    print("\n== F038 judge discovery finding rows ==")
    sb = scratch("fb1837_disc_")
    dd = sb / "judge_review" / "discovery"
    dd.mkdir(parents=True)
    header = "| class | probe | checked | disposition |\n|---|---|---|---|\n"
    for side in ("target", "v1"):
        rows = "".join(
            f"| class {i} | probe | {side}/f{i}.md | "
            + ("finding |" if i == 0 else "clean - checked: base/ |") + "\n"
            for i in range(5))
        (dd / f"{side}.md").write_text(header + rows, encoding="utf-8")
    errs, _w = pp.judge_discovery_problems(sb, {"kind": "judge", "label_map": {"v1": "a2"}})
    check("F038 a bare `finding` row is refused",
          any("without the required" in e for e in errs), errs)




def test_visual_and_raw_gates() -> None:
    print("\n== F025/F029/F098/F103/F104 ==")
    # F025: a fabricated EMPTY raw_data/ area is a failure, not a silent rmdir.
    root = scratch("fb1837_raw_")
    pristine = root / "non_revised"
    pristine.mkdir()
    cand = root / "cand"
    (cand / "raw_data").mkdir(parents=True)

    class RawCtx:
        pass

    rctx = RawCtx()
    rctx.pristine = pristine
    warns: list = []
    info = pp.enforce_readonly_raw_data(rctx, cand, warns)
    check("F025 a fabricated empty raw_data/ is reported",
          bool(info.get("failures")) and bool(warns), (info, warns))
    # F098: a >1 KiB whitespace-only PDF is not a render.
    stub = root / "stub.pdf"
    stub.write_bytes(b"%PDF-1.4\n" + b" " * 2000 + b"%%EOF\n")
    check("F098 a whitespace-only PDF body is refused",
          bool(pp._render_output_body_problem(stub)))
    real = root / "real.pdf"
    real.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    check("F098 a real PDF body passes", pp._render_output_body_problem(real) == "")
    # F104: placeholder class rows do not count as a D1 enumeration.
    sb = scratch("fb1837_gap_")
    r2 = sb / "guided_review" / "round2"
    r2.mkdir(parents=True)
    (r2 / "gap_table.md").write_text(
        "# D1\n\n| # | class | coverage |\n|---|---|---|\n"
        + "\n".join(f"| {i} | x | UNCOVERED |" for i in range(1, 26)) + "\n",
        encoding="utf-8")
    summary = pp.discovery_gap_summary(sb)
    check("F104 a 25-row table of `x` names no issue class",
          summary["rows"] == 0 and summary["uncovered"] == 0, summary)
    (r2 / "gap_table.md").write_text(
        "# D1\n\n| # | class | coverage |\n|---|---|---|\n"
        + "\n".join(f"| {i} | class question {i} | UNCOVERED |"
                    for i in range(1, 26)) + "\n", encoding="utf-8")
    check("F104 real class labels still count",
          pp.discovery_gap_summary(sb)["rows"] == 25)
    # F029/F103: one failed template render is an error; a denial is not a comparison.
    vsb = scratch("fb1837_vis_")
    (vsb / "venue_template" / "word").mkdir(parents=True)
    (vsb / "venue_template" / "word" / "venue.docx").write_bytes(b"x")
    (vsb / "visual_template").mkdir()
    (vsb / "visual_template" / "manifest.json").write_text(json.dumps({
        "renderer": "stub", "documents": [
            {"role": "venue", "source": "venue.docx", "pages": "2",
             "pdf": "venue.pdf", "ok": False, "error": "Word failed"},
            {"role": "main", "source": "main.docx", "pages": "3",
             "pdf": "main.pdf", "ok": True}]}), encoding="utf-8")
    art = vsb / "VISUAL.md"
    art.write_text("main.docx: 3 pages compared to the template.\n", encoding="utf-8")
    errs: list = []
    pp.check_visual_artifact(art, "visual", errs, [], render_roots=None, sandbox=vsb)
    check("F029 a failed template render is reported",
          any("FAILED template render" in e for e in errs), errs)
    art.write_text("main.docx: 3 pages were NOT visually compared to the template.\n",
                   encoding="utf-8")
    errs2: list = []
    pp.check_visual_artifact(art, "visual", errs2, [], render_roots=None, sandbox=vsb)
    check("F103 a denial does not satisfy the template comparison",
          any("does not compare against it" in e for e in errs2), errs2)




def test_state_and_attempts() -> None:
    print("\n== F039/F061/F112 load validation; F015/F020/F031/F057 ==")

    def _load(rec, pins=()):
        root = scratch("fb1837_load_")
        (root / "runs" / "r1_x").mkdir(parents=True)
        (root / "pipeline_config.json").write_text("{}", encoding="utf-8")
        (root / "state.json").write_text(json.dumps({
            "version": pp.STATE_VERSION, "runs": {"r1_x": rec}, "rounds": {},
            "pinned": list(pins), "log": []}), encoding="utf-8")
        buf = io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                pp.Ctx(root).load()
            return "loaded"
        except SystemExit:
            return buf.getvalue()

    check("F112 an unknown run status is damaged state",
          "unknown status" in _load({"kind": "judge", "round": 1,
                                     "sandbox": "runs/r1_x", "status": "done "}))
    check("F061 a non-integer pinned round is damaged state",
          "non-integer 'round'" in _load(
              {"kind": "judge", "round": 1, "sandbox": "runs/r1_x", "status": "done"},
              [{"id": "p1", "round": "r1"}]))
    check("F039 a string judge_index is damaged state",
          "non-integer 'judge_index'" in _load(
              {"kind": "judge", "round": 1, "sandbox": "runs/r1_x", "status": "done",
               "judge_index": "1", "label_map": {}}))
    # F015: a symlinked cached render is a cache MISS, never an OSError.
    root = scratch("fb1837_pdf_")
    link = root / "cached.pdf"
    outside = root / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4\n1 0 obj\n%%EOF\n")
    link.symlink_to(outside)
    try:
        rec = pp._reuse_pdf_record({("l", "r"): {"ok": True, "sha256": "d",
                                                 "kind": "latex",
                                                 "out_sha256": "x"}},
                                   "l", "r", "d", link, "latex")
        check("F015 a symlinked cached render is refused, not raised", rec is None)
    except OSError as exc:                                    # noqa: BLE001
        check("F015 a symlinked cached render is refused, not raised", False, exc)
    # F020: a symlinked package table is not read.
    corpus = scratch("fb1837_cold_") / "corpus"
    (corpus / "raw_data").mkdir(parents=True)
    secret = scratch("fb1837_secret_") / "secret.csv"
    secret.write_text("SECRET_HEADER\n1\n2\n", encoding="utf-8")
    (corpus / "raw_data" / "x.csv").symlink_to(secret)
    rows = pp.cold_start_table_inventory(corpus)
    check("F020 a symlinked .csv is refused by the inventory",
          bool(rows) and "SECRET_HEADER" not in json.dumps(rows)
          and "(unreadable)" in json.dumps(rows), rows)
    # F031: a whole-file `remove` needs its preimage.
    sb = scratch("fb1837_resp_")
    target = sb / "target"
    target.mkdir()
    probs = pp._response_change_span_problems(
        sb, target, [{"id": "R1", "changes": [
            {"file": "gone.md", "operation": "remove", "location": "p1",
             "before": "", "after": ""}]}])
    check("F031 a `remove` row without a preimage is refused",
          any("no `before`" in p for p in probs), probs)
    # F057: the ordinary archive removes the marker and reports success.
    sb2 = scratch("fb1837_marker_")
    (sb2 / "_pipeline_done.json").write_text("{}", encoding="utf-8")
    check("F057 a removable stale marker reports no failure",
          pp.archive_stale_marker(sb2, "r1_x") == []
          and not (sb2 / "_pipeline_done.json").exists())
    p05 = (ROOT / "paper_pipeline_parts" / "p05_state_corpus.py").read_text(encoding="utf-8")
    p06 = (ROOT / "paper_pipeline_parts" / "p06_postchecks.py").read_text(encoding="utf-8")
    p07 = (ROOT / "paper_pipeline_parts" / "p07_stage_quality_journal.py").read_text(
        encoding="utf-8")
    p14 = (ROOT / "paper_pipeline_parts" / "p14_tracking.py").read_text(encoding="utf-8")
    p15 = (ROOT / "paper_pipeline_parts" / "p15_pdf.py").read_text(encoding="utf-8")
    check("F003 the cover-letter gate fails closed when the scan cannot run",
          "cl_scan_ok" in p07 and "cover-letter gate is UNVERIFIED" in p07)
    check("F021 every tracking write refuses a symlinked parent",
          p14.count("_refuse_symlinked_parent(persist") >= 2)
    check("F022 the rescue refuses a symlinked package directory",
          "was NOT adopted" in p07)
    check("F063 a missing LaTeX job is a warning row, not StopIteration",
          "next(_latex_jobs, None)" in p15)
    check("F117 a non-object PDF manifest is coerced",
          "if not isinstance(stored, dict)" in p15)
    check("F065 a failed promotion restores the trial archive",
          "_unpromote" in p05)
    p11 = (ROOT / "paper_pipeline_parts" / "p11_defect_audit.py").read_text(encoding="utf-8")
    check("F068 an empty defect audit clears stale TP files",
          "no defect rows to audit" in p11
          and p11.count("_remove_audited_defect_reports(ctx, r)") >= 2)
    check("F114 a dangling prior_audit symlink is removed",
          "prior_audit_dir.exists() or prior_audit_dir.is_symlink()" in p05)
    check("F115 a partial copy fallback is removed",
          "rmtree_force(dest, ignore_errors=True)" in p05)
    check("F135 the READ-ONLY failure warning is emitted once",
          p06.count('warns.append("READ-ONLY input failure in the package: "') == 1)
    check("F147 compaction contains the state-supplied sandbox path",
          "contained_under_or_none(root, path_rel)" in p05)
    check("F086 the cover-letter row match compares basenames",
          "_row_names_document" in p06)
    check("F055 an unusable newer sheet does not supersede a valid one",
          "unusable_newer_sheets" in (
              ROOT / "paper_pipeline_parts" / "p08_selection_driver.py").read_text(
                  encoding="utf-8"))
    check("F145 tracking freshness contains every recorded path",
          "contained_under_or_none(ctx.root, out_rel)" in p14)
    check("F045 placeholder lookup requires the marker's own query",
          "if query == payload:" in p06 and "query in payload" not in p06)
    check("F054 the aspects half that owns M2 must produce M2_references.md",
          "want_m2_artifact" in p06
          and '(k == "M2_references.md") == (not part_b)' in p06)


def test_static_docs_and_assets() -> None:
    print("\n== assets/docs/shell: F049/F070/F124/F128/F129/F141/F149/F150 ==")
    p00 = (ROOT / "paper_pipeline_parts" / "p00_prelude.py").read_text(encoding="utf-8")
    for script in ("extract_acronyms.py", "extract_citations.py", "extract_numbers.py",
                   "extract_occurrences.py", "evidence_names.py"):
        check(f"F070 required bundle carries {script}", script in p00)
    d2p = (ROOT / "docx2pdf.sh").read_text(encoding="utf-8")
    check("F049 docx2pdf.sh does not delete the destination up front",
          'rm -f -- "$PDF"\n' not in d2p
          and 'rm -f -- "$PDF" "$PDF_TMP"' not in d2p)
    d2c = (ROOT / "docxcompare.sh").read_text(encoding="utf-8")
    check("F049 docxcompare.sh does not delete the destination up front",
          'rm -f -- "$OUTPUT"\n' not in d2c
          and 'rm -f -- "$OUTPUT" "$OUTPUT_TMP"' not in d2c)
    inst = (ROOT / "install_agent_tooling.sh").read_text(encoding="utf-8")
    check("F124 a failed replacement add restores the backed-up config",
          "codex_config_backup_path" in inst and "restored" in inst
          and "cp -p --" not in inst)
    check("F128 the set-article-type example carries --root",
          "set-article-type --list --root" in (ROOT / "README.md").read_text(encoding="utf-8"))
    p06 = (ROOT / "paper_pipeline_parts" / "p06_postchecks.py").read_text(encoding="utf-8")
    check("F129 the self-report warning no longer claims a ranking tie",
          "only used to break a statistical tie" not in p06
          and "reported and cross-checked only" in p06)
    p08 = (ROOT / "paper_pipeline_parts" / "p08_selection_driver.py").read_text(encoding="utf-8")
    check("F141 skipped tracking rows are not counted as NO file",
          'not c.get("ok") and not c.get("skipped")' in p08)
    g7 = (ROOT / ".paper_test" / "test_fix_bugs_20261119_g7_docs_config.py").read_text(
        encoding="utf-8")
    check("F149 the legend-spacing check pins the conditional rule",
          "must not be measured against a blanket" in g7)
    w1 = (ROOT / ".paper_test" / "test_fix_bugs_20261122_wave1.py").read_text(encoding="utf-8")
    check("F150 the harness falls back when tmp/ is read-only",
          "mkdtemp(prefix=\"s092-\", dir=base)" in w1 and w1.count("mkdtemp(") >= 2)


def test_repair_regressions() -> None:
    print("\n== REPAIR R01-R08: final-verification regressions ==")
    # R01: a comment and a tracked deletion INSIDE the live sectPr survive a
    # section splice byte-for-byte (the masked copy is for spans only).
    doc = ('<w:document xmlns:w="http://w" xmlns:r="http://r"><w:body><w:p><w:pPr>'
           '<w:sectPr><!-- <w:headerReference w:type="default" r:id="rIdX"/> -->'
           '<w:pgSz w:w="11906"/><w:del><w:r><w:delText>OLD</w:delText></w:r></w:del>'
           '</w:sectPr></w:pPr></w:p></w:body></w:document>')
    out, changed = df._apply_front_refs(doc, {"header_default_rid": "rId1"})
    comment = '<!-- <w:headerReference w:type="default" r:id="rIdX"/> -->'
    check("R01 front refs keep a comment and a tracked deletion in the live section",
          changed and comment in out and "<w:delText>OLD</w:delText>" in out
          and "rId1" in out, out[:400])
    tpl = ('<w:document xmlns:w="http://w"><w:body><w:p><w:pPr><w:sectPr>'
           '<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440"/>'
           '</w:sectPr></w:pPr></w:p></w:body></w:document>')
    out2, applied = df._adopt_page_geometry(doc, tpl)
    check("R01 page geometry keeps a comment and a tracked deletion",
          applied and comment in out2 and "<w:delText>OLD</w:delText>" in out2, out2[:400])
    # R02: a valid PDF larger than the 4 MiB head window keeps its trailer at
    # the end; a whitespace-only body of the same size is still refused.
    big = scratch("repair_r02_") / "big.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"0" * (5 * 1024 * 1024) + b"\n%%EOF\n")
    check("R02 a valid PDF over 4 MiB is a render",
          pp._render_output_body_problem(big) == "",
          pp._render_output_body_problem(big))
    stub = scratch("repair_r02s_") / "stub.pdf"
    stub.write_bytes(b"%PDF-1.4\n" + b" " * (5 * 1024 * 1024) + b"\n%%EOF\n")
    check("R02 a >4 MiB whitespace-only PDF is not a render",
          bool(pp._render_output_body_problem(stub)))
    # R03: only a finding DISPOSITION triggers the finding-shape gate.
    sb = scratch("repair_r03_")
    dd = sb / "judge_review" / "discovery"
    dd.mkdir(parents=True)
    header = "| class | probe | checked | disposition |\n|---|---|---|---|\n"
    (dd / "target.md").write_text(
        header + "".join(
            f"| class {i} | probe | base/main.md | "
            "clean -- checked: base/main.md (no finding) |\n" for i in range(5)),
        encoding="utf-8")
    errs, _w = pp.judge_discovery_problems(sb, {"kind": "judge"})
    check("R03 a clean row mentioning `no finding` is not a finding row", not errs, errs)
    (dd / "target.md").write_text(
        header + "| class 0 | probe | target/f0.md | finding |\n" + "".join(
            f"| class {i} | probe | base/main.md | clean -- checked: base/main.md |\n"
            for i in range(1, 5)), encoding="utf-8")
    errs, _w = pp.judge_discovery_problems(sb, {"kind": "judge"})
    check("R03 a bare `finding` disposition is still refused",
          any("without the required" in e for e in errs), errs)
    # R04: 1-3 digit counts are not thousands-separator quantities; a plain
    # 4-digit quantity still participates.
    rows = df.number_format_rows(["We processed 1,000 samples and 3 replicates."])
    check("R04 a one-digit count is not a FMT-T9h quantity",
          not [r for r in rows if r.get("rule") == "FMT-T9h"], rows)
    rows = df.number_format_rows(["A total of 42 patients and 1,000 cells."])
    check("R04 a two-digit count is not a FMT-T9h quantity",
          not [r for r in rows if r.get("rule") == "FMT-T9h"], rows)
    rows = df.number_format_rows(["1,000 samples and 2500 cells."])
    check("R04 a plain 4-digit quantity still participates",
          any(r.get("rule") == "FMT-T9h" for r in rows), rows)
    # R05: a non-sized `adds` is reported, never raised.
    try:
        probs = pp.audit_artifact_problems(
            {"round": 1, "dispositions": [], "adds": 5,
             "counts": {"confirmed": 0, "dropped": 0, "added": 0}, "notes": "ok"}, [])
        check("R05 a numeric `adds` is a problem, not a TypeError",
              any("'adds' is not a list" in p for p in probs), probs)
    except Exception as exc:                                     # noqa: BLE001
        check("R05 a numeric `adds` is a problem, not a TypeError", False,
              f"{type(exc).__name__}: {exc}")
    # R06: with a known round the authoritative validator requires the prompt's
    # round/counts/notes fields and rejects a foreign round.
    probs = pp.audit_artifact_problems({"dispositions": [], "adds": []}, [],
                                       expected_round=1)
    check("R06 a missing round/counts/notes is rejected when the round is known",
          any("no 'round'" in p for p in probs) and any("no 'counts'" in p for p in probs)
          and any("no 'notes'" in p for p in probs), probs)
    probs = pp.audit_artifact_problems(
        {"round": 2, "dispositions": [], "adds": [],
         "counts": {"confirmed": 0, "dropped": 0, "added": 0}, "notes": "ok"},
        [], expected_round=1)
    check("R06 a foreign round is rejected", any("not this run's round" in p for p in probs),
          probs)
    p07 = (ROOT / "paper_pipeline_parts" / "p07_stage_quality_journal.py").read_text(
        encoding="utf-8")
    check("R06 the authoritative postcheck passes the run's round",
          'audit_artifact_problems(audit, frozen_ids,\n'
          '                                           expected_round=rec.get("round"))' in p07)
    # R08: a spaced document name disposes its own FMT-CL1 row; a longer
    # superset filename still does not.
    sb_cl = scratch("repair_r08_")
    (sb_cl / "base").mkdir()
    (sb_cl / "guided_review" / "artifacts").mkdir(parents=True)
    real_scan, real_policy = pp.scan_format_in_sources, pp.format_policy_of
    pp.scan_format_in_sources = lambda *a, **k: {
        "rows": [{"rule": "FMT-CL1", "document": "cover letter.docx"},
                 {"rule": "FMT-CL1", "document": "other.docx"}]}
    pp.format_policy_of = lambda ctx: {}
    try:
        art = sb_cl / "guided_review" / "artifacts" / "M20_formatting.md"
        art.write_text("| rule | evidence | disposition |\n|---|---|---|\n"
                       "| FMT-CL1 | cover letter.docx is stamped | F-042: restyle it |\n"
                       "| FMT-CL1 | other.docx is stamped | F-043: restyle it |\n",
                       encoding="utf-8")
        check("R08 a spaced document name disposes its FMT-CL1 row",
              not pp.cover_letter_row_survival_problems(object(), sb_cl),
              pp.cover_letter_row_survival_problems(object(), sb_cl))
        art.write_text("| rule | evidence | disposition |\n|---|---|---|\n"
                       "| FMT-CL1 | cover letter.docx.backup is stamped | F-042: restyle |\n"
                       "| FMT-CL1 | other.docx is stamped | F-043: restyle it |\n",
                       encoding="utf-8")
        check("R08 a longer superset filename does not dispose the row",
              bool(pp.cover_letter_row_survival_problems(object(), sb_cl)))
    finally:
        pp.scan_format_in_sources, pp.format_policy_of = real_scan, real_policy


def main() -> int:
    test_ranking()
    test_coverage_gates()
    test_audit_helpers()
    test_docx_helpers()
    test_docx_front_and_lists()
    test_judge_discovery_shape()
    test_visual_and_raw_gates()
    test_state_and_attempts()
    test_text_tracking()
    test_static_docs_and_assets()
    test_repair_regressions()
    cleanup()
    if FAILS:
        print(f"\n{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nALL 2026-11-22 FIX-BUGS WAVE-1 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

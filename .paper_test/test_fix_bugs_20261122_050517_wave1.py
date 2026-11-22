#!/usr/bin/env python3
"""Regression checks for fix_bugs wave 1 (run 2026-11-22-050517).

Every check pins one candidate this wave re-validated on the tree. Each
assertion fails on the unpatched tree and passes after the smallest fix.
"""
from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_docx_format as fmt        # noqa: E402
import paper_pipeline as pp            # noqa: E402
import paper_dots_agent as dots        # noqa: E402
import paper_qwen_agent as qwen        # noqa: E402
import paper_dsh_runtime as rt         # noqa: E402
import agent_common.model_runtime as mrt  # noqa: E402

FAILS: list[str] = []


def check(label: str, cond, detail="") -> None:
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def test_coverage_gates() -> None:
    print("\n== F008/F010/F040/F049: coverage/disposition filler and negation ==")
    check("F008 a negated count closure is refused",
          not pp._audit_disposition_ok("0 findings -- nothing was checked"))
    check("F008 a genuine zero is accepted",
          pp._audit_disposition_ok("0 findings; the sweep was re-derived from M1"))
    check("F010 a base-verb negation is refused",
          not pp._coverage_disposition_ok("0 findings -- could not check"))
    check("F010 a contraction negation is refused",
          not pp._coverage_disposition_ok("clean -- basis: couldn't run"))
    check("F010 a named basis is accepted",
          pp._coverage_disposition_ok("clean -- basis: reports/M1_acronyms.md"))
    check("F040 an anonymous pointer is refused",
          not pp._coverage_reason_named("see above"))
    check("F040 an anonymous discussion is refused",
          not pp._coverage_reason_named("as discussed"))
    check("F049 a verdict-prefixed filler tail is refused",
          not pp._is_recorded_reason("OK — see above"))
    check("F049 a named reason is accepted",
          pp._is_recorded_reason("OK — a quoted article title, not a finding"))
    check("F035 a bare M1b heading is a missing audit",
          pp.m1b_audit_section_missing(
              "ACRONYM INVENTORY\n\n## M1b\n\nno table here\n"))


def test_removal_accounting() -> None:
    print("\n== F041/F047/F118: removal accounting ==")
    check("F041 a bare retention word closes nothing",
          not pp._deletion_disposition_ok("OK — survives"))
    check("F041 a bare location closes nothing",
          not pp._deletion_disposition_ok("OK — line 3"))
    check("F041 an identity claim still closes a duplicate",
          pp._deletion_disposition_ok("OK — duplicate; no fact lost"))
    check("F041 a named location plus a claim closes the row",
          pp._deletion_disposition_ok("OK — survives, line 3"))
    check("F047 an id-keyed list keeps the finding id",
          pp.ledger_final_status_map(
              {"F-1": [{"final_status": "manual-required"}]}) == {
                  "F-1": "manual-required"})
    src = (ROOT / "paper_pipeline_parts/p21_removal_accounting.py").read_text()
    psrc = (ROOT / "paper_pipeline_parts/p07_stage_quality_journal.py").read_text()
    check("F118 marker deletion is gated by the recorded mode",
          "allow_marker_delete: bool = True" in src
          and "allow_marker_delete=allow_marker_delete" in src
          and 'author_to_complete_mode_of(ctx) in ("readme", "off")' in psrc)


def test_docx_whitespace_and_quotes() -> None:
    print("\n== F013/F014/F015/F016/F038/F062/F064: legal XML spellings ==")
    check("F013 whitespace-closed instrText is read",
          fmt._part_has_zotero_item_field(
              b'<w:instrText> ADDIN ZOTERO_ITEM CSL_CITATION </w:instrText >'))
    ppr = ('<w:pPr><w:rPr><w:b/></w:rPr ><w:jc w:val="left"/></w:pPr>')
    out = fmt._insert_ppr_extra(ppr, '<w:rPr><w:i/></w:rPr>')
    check("F014 a whitespace-closed rPr is replaced, never duplicated",
          out.count("<w:rPr") == 1, out)
    para = '<w:p><w:r><w:t>a</w:t ></w:r><w:r><w:t>b</w:t></w:r></w:p>'
    check("F015 a whitespace-closed w:t does not swallow the next run",
          [t for _s, _e, t in fmt._iter_wt_elements(para)] == ["a", "b"],
          [t for _s, _e, t in fmt._iter_wt_elements(para)])
    numbering = ('<w:numbering><w:num w:numId="1"><w:abstractNumId w:val="1"/>'
                 '</w:num ><w:abstractNum w:abstractNumId="1"/></w:numbering>')
    ordered = fmt._reorder_numbering_groups(numbering, "", "", "")
    check("F016 a whitespace-closed w:num block stays one block",
          ordered.count("<w:num ") == 1 and "<w:num <w:abstractNum" not in ordered,
          ordered)
    check("F062 a single-quoted pStyle is remapped",
          fmt._remap_style_refs("<w:pStyle w:val='Heading1'/>",
                                {"Heading1": "H1"})[0] == "<w:pStyle w:val='H1'/>")
    check("F064 single-quoted extent geometry is read",
          fmt._attr_any("<wp:extent cx='123' cy='456'/>", "cx") == "123")
    fixes = fmt._ratio_fixes("<wp:extent cx='1000' cy='1000'/>", 2.0)
    check("F064 a single-quoted cy is rewritten in its own quoting",
          fixes and "cy='500'" in fixes[0][2], fixes)


def test_text_and_prose() -> None:
    print("\n== F046/F058/F091/F092/F094/F096/F102: parsers and classifiers ==")
    _lines, _caps, _aend = pp._tex_length_scan(
        "\\begin {abstract}Body.\\end {abstract}")
    check("F046 a space before the abstract group is legal",
          _aend is not None and "Body." in _lines, (_lines, _aend))
    check("F046 a space before a math environment is blanked",
          "Body" not in pp.blank_math_environments(
              "\\begin {equation}Body\\end {equation}"))
    check("F058 a transient DNS failure is retryable",
          not dots._permanent_transport_error(
              "[Errno -3] Temporary failure in name resolution"))
    check("F058 a permanent DNS failure stays permanent",
          dots._permanent_transport_error("[Errno -2] Name or service not known"))
    check("F091 a one-character typo in a short header is a near miss",
          pp._one_edit_apart("mixmhcpred", "mixmhcpreb"))
    check("F091 two unrelated names are not",
          not pp._one_edit_apart("mixmhcpred", "flowcytometry"))
    check("F092 a double-quoted declaration loses its quotes",
          pp._strip_declared_token('"data/x.tsv"') == "data/x.tsv")
    check("F092 a single-quoted declaration loses its quotes",
          pp._strip_declared_token("'data/x.tsv'") == "data/x.tsv")
    stale = (datetime.now(timezone.utc)
             - timedelta(days=pp.LOOKUP_CACHE_TTL_DAYS, hours=23)).isoformat()
    check("F094 an almost-one-day-over-TTL entry is stale",
          not pp._lookup_cache_fresh({"checked_at": stale}))
    fresh = (datetime.now(timezone.utc)
             - timedelta(days=pp.LOOKUP_CACHE_TTL_DAYS - 1, hours=23)).isoformat()
    check("F094 a within-TTL entry is fresh",
          pp._lookup_cache_fresh({"checked_at": fresh}))
    check("F096 p < 0.10 is not significant under the 0.05 rule",
          not pp._p_reports_significant("p < 0.10"))
    check("F096 p < 0.05 is significant",
          pp._p_reports_significant("p < 0.05"))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "HANDOFF.md"
        p.write_text(
            "# Manual steps\n\n"
            "- one real step\n\n"
            "```text\n"
            "| a | b |\n|---|---|\n| x | y |\n"
            "- a fenced bullet\n"
            "```\n")
        check("F102 a fenced table/bullet is not a manual step",
              pp.count_manual_steps(p) == 1, pp.count_manual_steps(p))
    check("F109 the report no longer promises an id rung",
          "only after that the id" not in
          (ROOT / "paper_pipeline_parts/p12_conflicts_decide.py").read_text())
    doc = (ROOT / "pairwise_scores.py").read_text()
    check("F123 the head-dump docstring no longer promises blank-line keeping",
          "Every physical line between markers is preserved" not in doc
          and "blank line between records is record separation" in doc)


def test_credentials_and_venues() -> None:
    print("\n== F026/F042/F060/F048/F095: credentials and identity collisions ==")
    check("F026 an explicit empty --api-key stays empty",
          qwen._qwen_api_key(type("A", (), {"api_key": ""})(), "url-secret") == "")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "venue_profiles"
        d.mkdir()
        # The duplicate (name "aaa.json", declares "zzz") is read BEFORE the
        # rightful owner ("zzz.json"), which used to hide the collision.
        (d / "aaa.json").write_text(json.dumps({"id": "zzz", "label": "dup"}))
        (d / "zzz.json").write_text(json.dumps({"id": "zzz", "label": "owner"}))
        found = pp.available_venue_profiles(Path(td))
        check("F042 the earlier duplicate is reported when the owner follows",
              bool((found.get("aaa") or {}).get("error")),
              (found.get("aaa") or {}).get("error"))
    check("F095 a hyphenated NCName prefix is declared",
          pp._namespace_declarations('xmlns:my-prefix="urn:x"') == {
              "my-prefix": "urn:x"})
    installer = (ROOT / "install_agent_tooling.sh").read_text()
    check("F060 the snapshot prune only matches the installer's version names",
          '"${tool_path}"-*; do' not in installer
          and '"${tool_path}"-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]-*' in installer)
    check("F048 the project Codex config is read from the checkout",
          '"$PWD/.codex/config.toml"' not in installer
          and '"$repo_dir/.codex/config.toml"' in installer)


def test_sanitizers_and_bounds() -> None:
    print("\n== F006/F030/F032/F074/F105: guards and bounds ==")
    import inspect
    src = inspect.getsource(pp.read_regular_file)
    check("F006 read_regular_file refuses a symlinked parent", 
          "_refuse_symlinked_read_parent" in src)
    bsrc = (ROOT / "paper_pipeline_parts/p06_postchecks.py").read_text()
    check("F030 the destination comparison is bounded",
          "read_text_bounded(dst" in bsrc or "read_regular_file(dst" in bsrc)
    usrc = (ROOT / "paper_pipeline_parts/p04_utils.py").read_text()
    check("F032 ZIP parts are read through a bounded stream",
          "MAX_DOCX_PART_BYTES + 1" in usrc)
    check("F074 the image loop skips analysis-code rasters",
          "if is_code_rel(prefix + rel):" in usrc)
    rsrc = (ROOT / "paper_redlines_adapter.py").read_text()
    check("F105 a broken optional import exits with the documented code",
          "except Exception as exc:" in rsrc and "... not importable" in rsrc
          or "is not importable" in rsrc)


def test_sanitizers_and_guards() -> None:
    print("\n== F001/F004/F009/F011/F020/F024/F027/F029/F043/F060/F067/F081: "
          "sanitizers and guards ==")

    def _docx(parts):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as z:
            for name, payload in parts.items():
                z.writestr(name, payload)
        return raw.getvalue()

    wdoc = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>'
    nested = _docx({"docProps/core.xml":
                    b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                    b'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Embedded Secret Author</dc:creator></cp:coreProperties>'})
    outer = _docx({"word/document.xml": wdoc,
                   "word/embeddings/embed1.xlsx": nested})
    out, _notes = pp._sanitize_ooxml_bytes(outer)
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        inner = z.read("word/embeddings/embed1.xlsx")
    with zipfile.ZipFile(io.BytesIO(inner)) as z:
        core = z.read("docProps/core.xml")
    check("F001 a nested OOXML object loses its author metadata",
          b"Embedded Secret Author" not in core, core[:80])

    utf16_core = (b"\xff\xfe" + (
        '<?xml version="1.0" encoding="UTF-16"?><cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>'
        'Utf16 Alice</dc:creator></cp:coreProperties>').encode("utf-16-le"))
    out, _notes = pp._sanitize_ooxml_bytes(
        _docx({"word/document.xml": wdoc, "docProps/core.xml": utf16_core}))
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        core = z.read("docProps/core.xml")
    check("F004 a UTF-16 docProps part is normalized and blanked",
          b"Utf16 Alice" not in core)

    comments = (b'<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b'<w:comment w:author="author"><w:p><w:r><w:t>As Alice of Lab X noted</w:t>'
                b'</w:r></w:p></w:comment></w:comments>')
    out, _notes = pp._sanitize_ooxml_bytes(
        _docx({"word/document.xml": wdoc, "word/comments.xml": comments}))
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        body = z.read("word/comments.xml")
    check("F024 a comment body (which can name the author) is blanked",
          b"As Alice of Lab X noted" not in body)

    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" '
           b'xmlns:dc="http://purl.org/dc/elements/1.1/"><title>Title</title>'
           b'<dc:creator>Alice Secret</dc:creator><rect/></svg>')
    out, _notes = pp._sanitize_svg_bytes(svg)
    check("F027 direct dc elements and title/desc text are removed",
          b"Alice Secret" not in out and b"<title>" not in out, out)

    xmp = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/" '
           b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:RDF>'
           b'<rdf:Description xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/" '
           b'xmpMM:DocumentID="uuid:SECRET"/></rdf:RDF></x:xmpmeta>')
    check("F029 an XMP DocumentID attribute is blanked",
          b"SECRET" not in pp._blank_xmp_fields(xmp))

    rtf = b'{\\rtf1{\\info{\\*\\company Acme Secret}{\\author Alice}}}'
    out, _notes = pp._sanitize_rtf_bytes(rtf)
    check("F081 an ignorable-destination identity group is blanked",
          b"Acme Secret" not in out, out)

    # F009: the reversed claim must not be rescued by an unrelated negation.
    def _unit(text):
        return {"text": text,
                "tokens": re.findall(r"[0-9A-Za-z]+", text.lower())}
    check("F009 a reversed claim spread across clauses is not contained",
          not pp._content_unit_contained(
              _unit("Drug X was not effective in trial A."),
              [{"text": "Drug X was effective in trial A. Safety was not acceptable."}]))
    check("F009 a genuine split merge is still contained",
          pp._content_unit_contained(
              _unit("Drug X was effective in trial A."),
              [{"text": "Safety was acceptable. Drug X was effective in trial A."}]))

    with tempfile.TemporaryDirectory() as td:
        sb = Path(td)
        (sb / "prior_audit" / "UNRESOLVED.md").mkdir(parents=True)
        check("F011 a staged prior-audit DIRECTORY is UNKNOWN, not empty",
              pp.prior_audit_observation_ids(sb) is None)
        (sb / "prior_round").mkdir()
        (sb / "prior_round" / "new_sweeps.md").symlink_to(sb / "missing")
        check("F011 a broken prior-sweep symlink is UNKNOWN, not empty",
              pp.prior_proposal_ids(sb) is None)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        outside = d / "outside"
        outside.write_text("keep", encoding="utf-8")
        (d / ".paper_model_write_test").symlink_to(outside)
        check("F020 the write probe does not follow a planted symlink",
              rt._writable(d, "model") and outside.read_text() == "keep")

    check("F043 a non-`r` relationship prefix is read",
          fmt._relationship_id("<rel:embed='rId5'/>", {"rel"}) == "rId5")
    rpr = '<w:rPr><!-- <w:color w:val="FF0000"/> --></w:rPr>'
    out, changed = fmt._rpr_set_emphasis(rpr, True)
    check("F067 a commented-out child is not an insertion anchor",
          changed and out.count("<w:i/>") == 1 and "</w:rPr>" in out)

    src = (ROOT / "paper_pipeline_parts/p06_postchecks.py").read_text()
    check("F007 a process failure clears the stale postcheck",
          src.count('rec.pop("postcheck", None)') >= 2)
    src33 = (ROOT / "paper_pipeline_parts/p09_setup.py").read_text()
    check("F033 staged-profile validation refuses a symlink",
          "and not (r / f\"{vid}{VENUE_PROFILE_SUFFIX}\").is_symlink()" in src33)
    src63 = (ROOT / "paper_docx_format_parts/p03_report_cli.py").read_text()
    check("F063 geometry splices are comment-masked",
          "_mask_noncontent(_live_sect_pr(body))" in src63)
    check("F068 a surviving stale tree refuses the rebuild",
          "if not rmtree_force(dest):" in
          (ROOT / "paper_pipeline_parts/p04_utils.py").read_text())
    check("F069 a duplicate-member DOCX is refused before the rewrite",
          "_docx_duplicate_member_problem(z)" in src63)
    check("F076 the header/footer scan resolves the binding prefix",
          "_attached_template_rid(m.group(0), prefixes)" in src63)
    check("F078 the main part is decoded through _ooxml_part_codec",
          'doc_xml, doc_encode = _ooxml_part_codec(data["word/document.xml"])' in src63)


def test_pipeline_bookkeeping() -> None:
    print("\n== F080/F085/F088/F093/F099/F100/F101/F107/F112/F117: bookkeeping ==")
    old_test = (ROOT / ".paper_test/test_fix_bugs_20261122_wave1.py").read_text()
    check("F080 the prior regression test no longer writes under debug_runs",
          'ROOT / "debug_runs"' not in old_test)
    check("F085 the not-materialized skip row is recorded once",
          "if row not in skipped:" in
          (ROOT / "paper_pipeline_parts/p14_tracking.py").read_text())
    check("F088 a claimed render with no PDF is not ok",
          "the renderer reported success but wrote no PDF" in
          (ROOT / "paper_pipeline_parts/p15_pdf.py").read_text())
    check("F093 a killed tunnel child is reaped",
          (ROOT / "paper_qwen_agent.py").read_text().count("_TUNNEL.wait(timeout=5)") >= 2)
    check("F099 an oversized selfcheck request is moved aside",
          "request.oversized-" in
          (ROOT / "paper_pipeline_parts/p08_selection_driver.py").read_text())
    check("F100 a failed sweep carries its partial removals",
          "err.partial = out" in
          (ROOT / "paper_pipeline_parts/p04_utils.py").read_text())
    check("F101 stdin is decoded after Buffer.concat",
          "Buffer.concat(chunks).toString" in
          (ROOT / "install_agent_tooling.sh").read_text())
    check("F107 the retry reset is persisted before the rebuild",
          "reset_run_record(rec)\n        # Persist the reset" in
          (ROOT / "paper_pipeline_parts/p16_retry.py").read_text())
    check("F112 materialization compares the walk's gaps too",
          "if not manifests_equal(" in
          (ROOT / "paper_pipeline_parts/p18_helpers.py").read_text())
    check("F117 the score model documents the recorded rule",
          pp.score_model_doc(rule="sign")["anti_regression_rule"].startswith("sign"))


def test_credentials_and_scanning() -> None:
    print("\n== F002/F003/F039/F050/F052/F055/F056/F066/F086: credentials and scans ==")
    safe, secret = mrt.split_endpoint_credentials(
        "https://host/v1?model=m&X-Amz-Signature=SECRETVAL")
    check("F003 a signature query credential is split out of the base URL",
          secret == "SECRETVAL" and "SECRETVAL" not in safe and "model=m" in safe,
          (safe, secret))
    safe, secret = mrt.split_endpoint_credentials(
        "https://host/v1?api-version=2024-01-01&jwt=TOK")
    check("F003 a jwt query credential is split out",
          secret == "TOK" and "TOK" not in safe and "api-version" in safe,
          (safe, secret))
    check("F039 a query is preserved but the path is appended before it",
          dots._request_url("https://host/v1?model=m", "/chat/completions")
          == "https://host/v1/chat/completions?model=m")
    check("F050 a malformed endpoint is a clean request error",
          dots._request("GET", "https://[bad/v1/models")[0] == 0)
    check("F052 the reader is filtered to one extension per pair pass",
          "exts=(ext,)" in
          (ROOT / "paper_pipeline_parts/p13_redlines.py").read_text())
    patterns = pp._pkg2_area_patterns(["code"])
    check("F055 a backtick-quoted bare area is reported",
          any(p.search("the code is in `code/`") for p in patterns))
    check("F055 a backtick-quoted area directory phrase is reported",
          any(p.search("the `code` directory") for p in patterns))
    check("F055 an unrelated word ending in the area name is not",
          not any(p.search("a barcode/reader") for p in patterns))
    usrc = (ROOT / "paper_pipeline_parts/p04_utils.py").read_text()
    check("F066 the prose corpus reader skips code/",
          usrc.count("if is_code_rel(prefix + rel):") >= 2)
    check("F056 the PKG-4 early return keeps absent-area figures",
          "if not carried_labels and not absent_labels:" in
          (ROOT / "paper_pipeline_parts/p12_conflicts_decide.py").read_text())
    check("F086 statistics rows use the deduplicated representative",
          "_champ_row(rd[\"agg\"], rd[\"stored\"])" in
          (ROOT / "paper_pipeline_parts/p12_conflicts_decide.py").read_text())
    msrc = (ROOT / "paper_model_agent.py").read_text()
    check("F002 the parse-failure message redacts the endpoint",
          "rt.redact_endpoint_url(str(cfg.get('endpoint')))" in msrc)
    check("F002/F003 the probe prints a redacted endpoint",
          "print(f\"endpoint: {rt.redact_endpoint_url(" in msrc)
    check("F061 the base/root refusal covers an explicit prefix",
          'basename -- "${ENV_PREFIX:-${ENV_NAME}}"' in
          (ROOT / "scripts/create-test-env.sh").read_text())
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "src"
        root.mkdir()
        (root / "real.txt").write_text("x", encoding="utf-8")
        (root / "link.txt").symlink_to(root / "real.txt")
        notes = []
        dst = Path(td) / "out"
        pp._merge_tree(root, dst, notes)
        check("F031 a skipped symlinked staged entry is a named note",
              any("skipped a symlinked staged entry" in n for n in notes), notes)
        outside = Path(td) / "outside"
        outside.mkdir()
        dlink = Path(td) / "dlink"
        dlink.symlink_to(outside, target_is_directory=True)
        try:
            pp._merge_tree(root, dlink, [])
            refused = False
        except OSError:
            refused = True
        check("F005 a symlinked destination is refused", refused)
        base = Path(td) / "store" / ".add-venue"
        base.mkdir(parents=True)
        (base / "nature-20260101T000000Z").symlink_to(outside,
                                                      target_is_directory=True)
        check("F034 a symlinked .add-venue candidate is not selected",
              pp.latest_add_venue_sandbox(Path(td) / "store", "nature") is None)


def test_remaining_gates() -> None:
    print("\n== F028/F036/F037/F045/F051/F053/F054/F059/F065/F075/F087: remaining gates ==")
    src = lambda rel: (ROOT / rel).read_text()
    check("F028 the --policy input is protected from the --json report",
          "Path(args.policy)" in src("paper_docx_format_parts/p03_report_cli.py"))
    trk = src("paper_pipeline_parts/p14_tracking.py")
    check("F036 repeated version ids are deduplicated",
          "dict.fromkeys(" in trk and 'v.strip() for v in str(args.version).split(",")' in trk)
    check("F036 a self-copy is skipped",
          "earlier.resolve() != persist_out.resolve()" in trk)
    check("F045 a duplicate opponent is dropped like aggregate_round",
          '_seen_opinions' in src("paper_pipeline_parts/p20_judge_conflicts.py")
          and '"duplicate_opponent"' in src("paper_pipeline_parts/p20_judge_conflicts.py"))
    check("F051 the success-path relay catches HTTPException",
          "http.client.HTTPException" in src("paper_model_agent.py"))
    pkg = src("paper_pipeline_parts/p12_conflicts_decide.py")
    import inspect
    check("F053 the MCB scan no longer pre-filters on the literal token",
          '"mcb" not in p.name.lower()' not in inspect.getsource(
              pp.scan_mcb_rule_conflicts))
    check("F054 a grid is selected by its header, not its filename",
          '"grid" not in p.name.lower()' not in pkg)
    check("F059 the short-read guard covers GET too",
          src("paper_agent_runtime_patch.py").count("def do_GET") >= 1)
    check("F065 the session id is read from a bounded transcript tail",
          "_open_regular_no_follow(log)" in
          src("paper_pipeline_parts/p22_resume_continuation.py"))
    check("F075 numeric finding ids are coerced in the pre-flight",
          "fid = str(f.get(\"id\") or \"\").strip()" in
          src("paper_pipeline_parts/p07_stage_quality_journal.py"))
    dep = src("install_dependencies.sh")
    check("F087 a failed git status is not a clean checkout",
          "_status_rc" in dep and "git status --porcelain 2>/dev/null || true" not in dep)
    exp = src("scripts/export-test-env.sh")
    check("F037 every pip-only list pipeline stage is checked",
          "PIPESTATUS" in exp and "_no_pypi_tmp" in exp
          and "|| true" not in exp.split("requirements.list_e_no_pypi")[0])


def main() -> int:
    test_coverage_gates()
    test_removal_accounting()
    test_docx_whitespace_and_quotes()
    test_text_and_prose()
    test_credentials_and_venues()
    test_sanitizers_and_bounds()
    test_sanitizers_and_guards()
    test_pipeline_bookkeeping()
    test_credentials_and_scanning()
    test_remaining_gates()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("ALL fix_bugs_20261122_050517_wave1 REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

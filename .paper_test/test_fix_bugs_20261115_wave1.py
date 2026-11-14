#!/usr/bin/env python3
"""Regression checks for the 2026-11-15 fix-bugs wave 1 (F-* candidates).

Each check pins one candidate this wave re-validated on the tree and repaired.
Hermetic: every fixture lives under tempfile.mkdtemp(); CLI checks drive their
own root under that directory.

Run:  python3 .paper_test/test_fix_bugs_20261115_wave1.py
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1115wave1_pp", "paper_pipeline.py")
fmt = load("fb1115wave1_fmt", "paper_docx_format.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *args],
                          cwd=str(cwd or WS), capture_output=True, text=True, timeout=300)


def fmt_cli(*args, cwd):
    return subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), *args],
                          cwd=str(cwd), capture_output=True, text=True, timeout=300)


def make_source(tmp: Path) -> Path:
    src = tmp / "src"
    src.mkdir()
    (src / "main.md").write_text(
        "# Title\n\n## Abstract\nText.\n\n## Introduction\nText.\n", encoding="utf-8")
    return src


def make_root(tmp: Path, *extra) -> Path:
    src = make_source(tmp)
    root = tmp / "root"
    res = cli("setup", "--source", str(src), "--root", str(root), "--rounds", "1", *extra)
    check("fixture: setup succeeds", res.returncode == 0, res.stderr[-400:])
    return root


# ---------------------------------------------------------------------------
# F17/F18/F19/F20 -- the CLI's documented usage code and --only contract
# ---------------------------------------------------------------------------
def test_cli_contracts() -> None:
    print("\n== F17/F18/F19/F20: CLI usage codes and --only ==")
    tmp = scratch("fb1115_cli_")
    res = cli("retry", "--root", str(tmp / "none"), "--run", "a", "--runs", "b")
    check("F18 two retry selectors are an argparse usage error (exit 2)",
          res.returncode == 2 and "not allowed with argument" in res.stderr,
          f"rc={res.returncode} {res.stderr[-200:]}")
    root = make_root(tmp)
    res = cli("run", "--root", str(root), "--only", "nosuchthing", "--manual", "--no-wait")
    check("F17 an unknown --only stage exits 2",
          res.returncode == 2 and "unknown stage" in res.stderr,
          f"rc={res.returncode} {res.stderr[-200:]}")
    res = cli("run-decide", "--root", str(root), "--only", "w2", "--manual", "--no-wait")
    check("F19 run-decide --only does not start the decide phase",
          res.returncode == 0 and "the decide phase is not started" in res.stdout,
          f"rc={res.returncode} {res.stdout[-200:]}")
    res = cli("setup", "--help")
    check("F20 --review-scope help no longer claims an integer/list pair",
          "integer/list pair" not in res.stdout
          and "same enum strings, same list rules" in res.stdout,
          res.stdout[-200:])


# ---------------------------------------------------------------------------
# F27 -- a figure RANGE is not a legend
# ---------------------------------------------------------------------------
def test_legend_range() -> None:
    print("\n== F27: 'Figures 1-3 show' is body prose, not a caption ==")
    check("F27 a figure range is not a legend",
          fmt.LEGEND_RE.match("Figures 1-3 show the results.") is None)
    check("F27 a real legend still matches",
          bool(fmt.LEGEND_RE.match("Figure 1. A real caption title.")))
    check("F27 a supplementary legend still matches",
          bool(fmt.LEGEND_RE.match("Supplementary Fig. 4: A real caption.")))


# ---------------------------------------------------------------------------
# F31 -- a column SUM does not prove a maximum/minimum claim
# ---------------------------------------------------------------------------
def test_aggregate_guard() -> None:
    print("\n== F31: a SUM cannot prove an extreme-value claim ==")
    hit = {"kind": "sum", "source": "sum of column yield", "column": "yield",
           "file": "t.csv"}
    row = {"number": "9", "sentence": "The maximum yield was 9."}
    check("F31 the max claim is refused", fmt._number_proof_context_ok(row, hit) is False)
    row2 = {"number": "9", "sentence": "The yield was 9."}
    check("F31 an unqualified value is still provable",
          fmt._number_proof_context_ok(row2, hit) is True)
    check("F31 a MAX aggregate still proves 'maximum'",
          fmt._number_proof_context_ok(
              {"number": "9", "sentence": "The maximum yield was 9."},
              dict(hit, kind="max", source="max of column yield")) is True)


# ---------------------------------------------------------------------------
# F35 -- a two-column pipe table without edge pipes is a table
# ---------------------------------------------------------------------------
def test_two_column_pipe_table() -> None:
    print("\n== F35: a two-column pipe table is read ==")
    header, body = fmt._simple_table("sample | yield\n1 | 2\n3 | 4\n")
    check("F35 the two-column header is read", header == ["sample", "yield"], repr(header))
    check("F35 the rows are read", body == [["1", "2"], ["3", "4"]], repr(body))


# ---------------------------------------------------------------------------
# F51 -- a pct/auto row is not rewritten with a twip value
# ---------------------------------------------------------------------------
def _cell(width: int, text: str, typ: str = "dxa") -> str:
    return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="{typ}"/></w:tcPr>'
            f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>')


def test_table_pct_not_rewritten() -> None:
    print("\n== F51: table_layout_fixes refuses a non-dxa row ==")
    doc = (f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>'
           '<w:tbl><w:tblPr><w:tblW w:w="6000" w:type="dxa"/></w:tblPr>'
           '<w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="4000"/></w:tblGrid>'
           '<w:tr>' + _cell(2000, "A") + _cell(4000, "B") + '</w:tr>'
           '<w:tr>' + _cell(2500, "a", "pct") + _cell(3000, "b", "pct") + '</w:tr>'
           '</w:tbl></w:body></w:document>')
    edits = fmt.table_layout_fixes(doc, [{"rule": "FMT-TB5", "_col": 0, "_need": 3000}])
    check("F51 no edit is emitted for the pct table", edits == [], repr(edits))
    check("F51 the pct geometry is untouched",
          'w:w="2500" w:type="pct"' in fmt.apply_edits(doc, edits))


# ---------------------------------------------------------------------------
# F55/F56 -- validate a bare relative .tex; an all-SKIP run is not success
# ---------------------------------------------------------------------------
def test_validate_paths() -> None:
    print("\n== F55/F56: validate puts the compile in the scratch and refuses all-SKIP ==")
    if not any(shutil.which(x) for x in ("latexmk", "xelatex", "pdflatex")):
        print("[skip] no TeX engine on PATH")
        return
    tmp = scratch("fb1115_tex_")
    (tmp / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nHello.\n\\end{document}\n",
        encoding="utf-8")
    res = fmt_cli("validate", "main.tex", cwd=tmp)
    check("F55 a bare relative main.tex compiles", res.returncode == 0 and "compiled" in res.stdout,
          f"rc={res.returncode} {res.stdout[-300:]} {res.stderr[-200:]}")
    frag = tmp / "frag"
    frag.mkdir()
    (frag / "section.tex").write_text("\\section{X}\nBody.\n", encoding="utf-8")
    res = fmt_cli("validate", str(frag), cwd=tmp)
    check("F56 fragment-only validation is not a pass",
          res.returncode == 2 and "nothing was compiled or validated" in res.stdout,
          f"rc={res.returncode} {res.stdout[-300:]}")


# ---------------------------------------------------------------------------
# F81 -- generated LaTeX escapes section titles
# ---------------------------------------------------------------------------
def test_latex_title_escape() -> None:
    print("\n== F81: render_latex_template escapes section titles ==")
    tex = pp.render_latex_template(
        "demo", {"sections": [{"title": "Results & Discussion", "level": 1,
                               "mean_position": 1.0}]})
    check("F81 '&' is escaped", "\\section{Results \\& Discussion}" in tex,
          [ln for ln in tex.splitlines() if "section" in ln][:3])
    tex2 = pp.render_latex_template(
        "demo", {"sections": [{"title": "100% Results", "level": 1,
                               "mean_position": 1.0}]})
    check("F81 '%' is escaped", "\\section{100\\% Results}" in tex2,
          [ln for ln in tex2.splitlines() if "section" in ln][:3])


# ---------------------------------------------------------------------------
# F117/F128 -- path normalisation and a hostile pid
# ---------------------------------------------------------------------------
def test_small_helpers() -> None:
    print("\n== F117/F128: path normalisation and pid liveness ==")
    check("F117 './/x' normalises to a relative 'x'",
          pp.strip_leading_dot_slash(".//x") == "x",
          repr(pp.strip_leading_dot_slash(".//x")))
    check("F117 a normal './a/b' is unchanged",
          pp.strip_leading_dot_slash("./a/b") == "a/b")
    check("F128 an out-of-range pid reads as not alive",
          pp.pid_alive(2 ** 63) is False)
    check("F128 zero still reads as not alive", pp.pid_alive(0) is False)


# ---------------------------------------------------------------------------
# F37/F48/F59/F28 -- OOXML quoting and generated rPr
# ---------------------------------------------------------------------------
def _zip(path: Path, parts: dict) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return path


def _content_types() -> str:
    return (f'<?xml version="1.0"?><Types xmlns="{PKG_REL.replace("relationships", "content-types")}">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/></Types>')


def test_ooxml_quoting() -> None:
    print("\n== F37/F48/F59/F28: OOXML quoting and generated properties ==")
    tmp = scratch("fb1115_ooxml_")
    settings = (f'<?xml version="1.0"?><w:settings xmlns:w="{W}" xmlns:r="{R}">'
                "<w:attachedTemplate r:id='rId9'/></w:settings>")
    settings_rels = (f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}">'
                     "<Relationship Id='rId9' Type='" + R + "/attachedTemplate' "
                     "Target='file:///C:/Users/x/t.dotx'/></Relationships>")
    src = _zip(tmp / "in.docx", {
        "[Content_Types].xml": _content_types(),
        "_rels/.rels": f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}"/>',
        "word/document.xml": (f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>'
                              "<w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>"),
        "word/settings.xml": settings,
        "word/_rels/settings.xml.rels": settings_rels,
    })
    out = tmp / "out.docx"
    res = fmt.strip_local_path_links(src, out)
    check("F37 a single-quoted attachedTemplate is repaired", res.get("ok") is True,
          str(res)[:300])
    with zipfile.ZipFile(out) as z:
        left = z.read("word/settings.xml").decode("utf-8")
    check("F37 no live r:id remains", "attachedTemplate" not in left, left[-200:])

    hdr_rels = (f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}">'
                "<Relationship Id='rId1' Type='" + R + "/header' "
                "Target='header1.xml'/></Relationships>")
    doc = (f'<?xml version="1.0"?><w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>'
           "<w:p><w:r><w:t>Hello</w:t></w:r></w:p><w:sectPr>"
           "<w:headerReference w:type='default' r:id='rId1'/></w:sectPr>"
           "</w:body></w:document>")
    refs = fmt.referenced_header_footer_parts(
        {"word/_rels/document.xml.rels": hdr_rels.encode("utf-8"),
         "word/header1.xml": b""}, doc)
    check("F59 a single-quoted reference is found", refs == {"word/header1.xml"}, repr(refs))

    styles = {"S": {"sz": '24"/><w:evil w:x="y"/>'}, "D": {"sz": "20"}}
    inner = '<w:r><w:t>tail</w:t></w:r>'
    injected = fmt._caption_continuation_runs(inner, styles, "S", "D")
    check("F48 a non-numeric style size is not interpolated",
          "w:evil" not in injected, injected[:200])
    normal = fmt._caption_continuation_runs(
        inner, {"S": {"sz": "24"}, "D": {"sz": "20"}}, "S", "D")
    check("F48 a numeric size is still pinned", '<w:sz w:val="24"/>' in normal, normal)

    # F28: an absolute /word/header1.xml target resolves (and the logo is seen).
    header = _zip(tmp / "hdr.docx", {
        "[Content_Types].xml": _content_types(),
        "_rels/.rels": f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}"/>',
        "word/document.xml": (f'<?xml version="1.0"?><w:document xmlns:w="{W}" xmlns:r="{R}">'
                              '<w:body><w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr>'
                              "<w:r><w:t>Title</w:t></w:r></w:p><w:sectPr>"
                              "<w:headerReference w:type='default' r:id='rId1'/>"
                              "</w:sectPr></w:body></w:document>"),
        "word/_rels/document.xml.rels": (f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}">'
                                         "<Relationship Id='rId1' Type='" + R + "/header' "
                                         "Target='/word/header1.xml'/></Relationships>"),
        "word/header1.xml": (f'<?xml version="1.0"?><w:hdr xmlns:w="{W}"><w:p><w:r>'
                             "<w:drawing/></w:r></w:p></w:hdr>"),
    })
    rep = fmt.docx_front_matter_report(header)
    check("F28 an absolute header target resolves", rep.get("first_header") is True,
          repr(rep)[:300])
    check("F28 the logo in that header is seen", rep.get("logo_header") is True,
          repr(rep)[:300])


# ---------------------------------------------------------------------------
# F65 -- a .txt exemplar is parsed (or skipped), never an empty record
# ---------------------------------------------------------------------------
def test_txt_exemplar() -> None:
    print("\n== F65: .txt exemplars carry structure ==")
    tmp = scratch("fb1115_txt_")
    p = tmp / "sample.txt"
    p.write_text("# Title\n\n## Introduction\n\n## Methods\n", encoding="utf-8")
    rec = pp.extract_manuscript_structure(p)
    check("F65 markdown headings in .txt are read",
          [s["title"] for s in rec.get("sections") or []] == ["Introduction", "Methods"],
          repr(rec)[:300])
    q = tmp / "flat.txt"
    q.write_text("No headings here at all.\n", encoding="utf-8")
    n = pp.extract_manuscript_structure(q)
    check("F65 a heading-less .txt is reported skipped, not a record",
          n.get("skipped") and "sections" not in n, repr(n)[:300])


# ---------------------------------------------------------------------------
# F219/F220/F221 -- the setup/set-* refusal contracts
# ---------------------------------------------------------------------------
def test_setup_contracts() -> None:
    print("\n== F219/F220/F221: setup refusals ==")
    tmp = scratch("fb1115_setup_")
    src = make_source(tmp)
    res = cli("setup", "--source", str(src), "--root", str(tmp / "r219"),
              "--rounds", "1", "--strict-venue", "--journal", "Unrelated")
    check("F219 setup --strict-venue refuses with the usage code 2",
          res.returncode == 2 and "--strict-venue" in res.stderr,
          f"rc={res.returncode} {res.stderr[-200:]}")
    res = cli("setup", "--source", str(src), "--root", str(tmp / "r220"),
              "--rounds", "0", "--round-indices", "2")
    check("F220 --rounds 0 is accepted when --round-indices supplies the plan",
          res.returncode == 0, f"rc={res.returncode} {res.stderr[-300:]}")
    res = cli("setup", "--source", str(src), "--root", str(tmp / "r221"),
              "--rounds", "1", "--revision-mode", "resubmit",
              "--journal-feedback-from", "Evil\nJournal")
    check("F221 a newline in --journal-feedback-from is a usage error",
          res.returncode == 2 and "one line" in res.stderr,
          f"rc={res.returncode} {res.stderr[-200:]}")


# ---------------------------------------------------------------------------
# Second batch -- small profile/prompt/gate defects
# ---------------------------------------------------------------------------
def test_venue_profile_small() -> None:
    print("\n== F77/F79/F82: venue profile and role matcher ==")
    check("F77 Supporting_Information.docx is supplementary",
          pp.docx_document_role("Supporting_Information.docx") == "supp",
          pp.docx_document_role("Supporting_Information.docx"))
    check("F77 a plain 'support' file stays main",
          pp.docx_document_role("support.docx") == "main")
    try:
        pp.normalize_venue_profile(
            {"id": "demo", "label": "Demo",
             "style_limits": {"sentence_words": {"bdy": 40}}})
        err = ""
    except pp.VenueProfileError as e:
        err = str(e)
    check("F79 a misspelled sentence_words section key is reported",
          "bdy" in err and "section kind" in err, err[:300])
    check("F82 the venue norm names the profile's tables.caption policy",
          "`tables.caption`" in pp.VENUE_NORM_RULES
          and "immediately before its table" not in pp.VENUE_NORM_RULES)


def test_journal_mode_small() -> None:
    print("\n== F89/F90/F91: feedback streams and config values ==")
    tmp = scratch("fb1115_modes_")
    ctx = type("C", (), {})()
    ctx.cfg = {"revision_mode": "continue"}
    ctx.pristine = tmp
    check("F89 continue mode reads no human feedback",
          pp.journal_feedback_files(ctx) == [], repr(pp.journal_feedback_files(ctx)))
    check("F89 continue mode reads no LLM feedback",
          pp.journal_llm_feedback_files(ctx) == [])
    ctx2 = type("C", (), {})()
    ctx2.cfg = {"caption_limit": "300 words", "caption_limit_source": "operator"}
    try:
        pp.caption_limit_of(ctx2)
        refused = False
    except SystemExit:
        refused = True
    check("F90 a non-numeric operator caption limit is refused", refused)
    try:
        pp._atc_mode(0)
        refused = False
    except SystemExit:
        refused = True
    check("F91 an int 0 author_to_complete is refused, not read as default", refused)
    check("F91 None still selects the default", pp._atc_mode(None) == "readme")


def test_review_gate_ids() -> None:
    print("\n== F151/F156: padded check ids and a real int category ==")
    tmp = scratch("fb1115_gate_")
    sb = tmp / "sb"
    (sb / "base").mkdir(parents=True)
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    row = {"id": "F-001", "location": "base/main.md:1", "check": "M01",
           "evidence": "quote", "explanation": "why", "severity": "Major",
           "category": 3, "status": "resolvable"}
    fj = {"submission_dir": "./base", "findings": [row],
          "coverage": [{"check": c, "disposition": "clean -- basis: artifacts/M1.md"}
                       for c in list(pp.REQUIRED_REVIEW_CHECKS) + ["M19", "M18"]]}
    (sb / "guided_review" / "findings.json").write_text(
        __import__("json").dumps(fj), encoding="utf-8")
    (sb / "guided_review" / "findings.md").write_text("# findings\n", encoding="utf-8")
    errs, warns = [], []
    pp.check_review_contract(type("C", (), {"cfg": {}})(), sb, fj, errs, warns)
    check("F151 a padded M01 check id is accepted",
          not any("not an M/J check id" in e for e in errs),
          [e[:120] for e in errs if "M/J" in e])
    r2 = sb / "guided_review" / "round2"
    r2.mkdir(parents=True)
    (r2 / "findings_extra.json").write_text(__import__("json").dumps({"findings": [
        {"id": "X-901", "location": "base/main.md:1", "check": "M20",
         "category": "3", "severity": "Major", "evidence": "quote",
         "explanation": "why"}]}), encoding="utf-8")
    derrs, _dwarns = pp.discovery_contract_problems(sb)
    check("F156 a string category is refused by the discovery gate",
          any("category" in e and "X-901" in e for e in derrs),
          [e[:160] for e in derrs if "X-901" in e])


def test_deletion_and_aux_small() -> None:
    print("\n== F206/F262: deletion disposition and an auxiliary output root ==")
    check("F206 'moved to Methods' is a reason",
          pp._deletion_disposition_ok("OK - moved to Methods"))
    check("F206 'merged into Results' is a reason",
          pp._deletion_disposition_ok("OK - merged into Results"))
    check("F206 the one-token filler is still refused",
          pp._deletion_disposition_ok("OK - x") is False)
    tmp = scratch("fb1115_aux_")
    (tmp / "redlines").write_text("not a directory", encoding="utf-8")
    try:
        pp.ensure_aux_output_root(tmp, "redlines")
        refused = False
    except SystemExit:
        refused = True
    check("F262 a regular file at <root>/redlines is refused", refused)


def test_convention_helpers() -> None:
    print("\n== F270/F271/F274/F276: paper-review extractors ==")
    conv = load("fb1115_conv", "paper-skills/paper-review/scripts/enumerate_conventions.py")
    occ = load("fb1115_occ", "paper-skills/paper-review/scripts/extract_occurrences.py")
    check("F270 'Supplementary Tables' ends the reference region",
          bool(conv._REF_END_RE.match("Supplementary Tables")))
    centre = [v for name, forms in conv.CURATED_FAMILIES
              if "er/-re" in name for v in forms]
    check("F271 'centred' is enumerated", "centred" in centre, repr(centre))
    check("F271 'centring' is enumerated", "centring" in centre, repr(centre))
    check("F271 'centering' is enumerated", "centering" in centre, repr(centre))
    pat = occ.variant_pattern("3", "value")
    check("F274 '3 × 100' is not the value 3", pat.search("3 × 100") is None)
    check("F274 '3 × 10^0' is still the value 3", bool(pat.search("3 × 10^0")))
    tmp = scratch("fb1115_ext_")
    (tmp / "corpus").mkdir()
    (tmp / "corpus" / "PAPER.TEX.txt").write_text(
        "\\cite{key1}\n% \\cite{hidden}\n", encoding="utf-8")
    (tmp / "corpus" / "REFS.BIB.txt").write_text(
        "@article{key1, title={T}, author={A}, year={2020}}\n", encoding="utf-8")
    ext = WS / "paper-skills/paper-review/scripts/extract_citations.py"
    res = subprocess.run([sys.executable, str(ext), "--work", str(tmp),
                          "--out", str(tmp / "out")], capture_output=True, text=True,
                         timeout=120)
    import json as _json
    data = _json.loads((tmp / "out" / "artifacts" / "M2_citations.json").read_text())
    check("F276 an uppercase .TEX is read as LaTeX",
          res.returncode == 0 and data.get("tex_callouts")
          and "key1" in str(data.get("tex_callouts")), str(data)[:300])
    check("F276 a commented-out cite is not a call-out",
          "hidden" not in str(data.get("tex_callouts")), str(data.get("tex_callouts")))
    check("F276 an uppercase .BIB is read", bool(data.get("bib_entries")),
          str(data.get("bib_entries"))[:200])


def test_report_and_gate_small() -> None:
    print("\n== F64/F100/F152/F153/F173: report status, prompts, prior list, DOI ==")
    dr = load("fb1115_dr", "paper_pipeline_parts/decision_report.py")
    lines = dr.header_lines(
        generated="x", root="/r", version="1", config_line="- c", venue_lines=[],
        certification={}, verdict="X", clean_readme_name="r.md", pin_count=1,
        integrity={"hash_checks": "skipped", "pristine_ok": True,
                   "pristine_detail": "not verified (--skip-hash)", "pinned_errors": []},
        problems=[])
    text = "\n".join(lines)
    check("F64 --skip-hash is reported as not verified, not ok",
          "pristine original: not verified (--skip-hash)" in text
          and "pristine original: ok" not in text, text[-400:])
    src = (WS / "paper_pipeline_parts/p03_prompts.py").read_text(encoding="utf-8")
    check("F100 the prompts no longer claim a <VERSION> substitution",
          'normalized to "<VERSION>"' not in src and "references inside file contents are REMOVED" in src)
    check("F173 a bolded DOI cleans to the plain DOI",
          pp._clean_fact_token("10.1000/abc**") == "10.1000/abc",
          pp._clean_fact_token("10.1000/abc**"))
    tmp = scratch("fb1115_frozen_")
    sb = tmp / "sb"
    (sb / "guided_review").mkdir(parents=True)
    (sb / "guided_review" / "findings.json").write_text("{not json", encoding="utf-8")
    ctx = type("C", (), {})()
    ctx.sandbox_of = lambda rec: sb
    check("F153 an unparseable frozen review is None, not zero",
          pp.frozen_findings_total(ctx, {}) is None, pp.frozen_findings_total(ctx, {}))
    sb2 = tmp / "sb2"
    (sb2 / "base").mkdir(parents=True)
    (sb2 / "prior_round").mkdir(parents=True)
    (sb2 / "guided_review" / "artifacts").mkdir(parents=True)
    (sb2 / "prior_round" / "findings.json").write_text("{not json", encoding="utf-8")
    fj = {"submission_dir": "./base", "findings": [],
          "coverage": [{"check": c, "disposition": "clean -- basis: artifacts/M1.md"}
                       for c in list(pp.REQUIRED_REVIEW_CHECKS) + ["M19", "M18"]]}
    (sb2 / "guided_review" / "findings.json").write_text(
        __import__("json").dumps(fj), encoding="utf-8")
    (sb2 / "guided_review" / "findings.md").write_text("# findings\n", encoding="utf-8")
    errs, _warns = [], []
    pp.check_review_contract(type("C", (), {"cfg": {}})(), sb2, fj, errs, _warns)
    check("F152 an unparseable prior-round list fails the reconciliation gate",
          any("could not be parsed" in e for e in errs),
          [e[:140] for e in errs if "prior" in e])


def main() -> int:
    print("== 2026-11-15 fix-bugs wave 1 regression checks ==")
    test_cli_contracts()
    test_legend_range()
    test_aggregate_guard()
    test_two_column_pipe_table()
    test_table_pct_not_rewritten()
    test_validate_paths()
    test_latex_title_escape()
    test_small_helpers()
    test_ooxml_quoting()
    test_txt_exemplar()
    test_setup_contracts()
    test_venue_profile_small()
    test_journal_mode_small()
    test_review_gate_ids()
    test_deletion_and_aux_small()
    test_convention_helpers()
    test_report_and_gate_small()
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

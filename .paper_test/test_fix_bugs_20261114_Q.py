#!/usr/bin/env python3
"""Group Q regression checks: venue-profile validation and prompt paging.

Run:  conda run -n paper-refine-test python .paper_test/test_fix_bugs_20261114_Q.py

Every check is self-contained (tempfile fixtures only) and pins one confirmed
fix from debug run 20261114-045738:
  F190 an invalid recorded venue_profile snapshot is reported, not discarded;
  F191 a pre-schema snapshot inherits the venue's style_limits;
  F192 falsy non-object prompt/submission/image_dpi/figure_text/style_limits fail;
  F193 venue-level captions / cover-letter limits apply next to article_types;
  F195 an unreadable profile file that blocks inheritance is reported;
  F197 a malformed .official/requirements.json fails the pack build;
  F198 a malformed pack structure.json is reported, not read as "no pack";
  F199 a plain DOCX body paragraph cannot satisfy a mandatory section;
  F200 a stage prompt with nothing paged never points at the missing file;
  F201 duplicate block titles get unique sections in prompt order;
  F203 the synthesized findings.md actually lists its X-9xx rows.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
WS = HERE.parent
spec = importlib.util.spec_from_file_location("paper_fix_q", str(WS / "paper_pipeline.py"))
P = importlib.util.module_from_spec(spec)
sys.modules["paper_fix_q"] = P
spec.loader.exec_module(P)
FAILS = []
TMPDIRS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'ok ' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def ctx_for(root: Path, cfg: dict):
    return SimpleNamespace(cfg=cfg, root=root,
                           cfg_path=root / "pipeline_config.json", state={})


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# F190
# ---------------------------------------------------------------------------
def test_f190_invalid_snapshot_is_reported() -> None:
    print("\n== F190: an invalid recorded snapshot is not silently discarded ==")
    root = scratch("q190_")
    cfg = {"venue": "generic",
           "venue_profile": {"id": "generic", "article_types": []}}
    ctx = ctx_for(root, cfg)
    base, err = P.venue_profile_base(ctx)
    check("F190 the invalid snapshot does not fall back to the profile file",
          base is None, repr(base))
    check("F190 the error names the recorded snapshot",
          err is not None and "snapshot" in str(err), str(err))
    _notes, problems = P.venue_config_findings(ctx)
    check("F190 venue_config_findings reports the broken snapshot",
          any("snapshot" in p and "cannot be used" in p for p in problems),
          str(problems)[:300])


# ---------------------------------------------------------------------------
# F191
# ---------------------------------------------------------------------------
def test_f191_snapshot_inherits_style_limits() -> None:
    print("\n== F191: a pre-schema snapshot inherits style_limits ==")
    root = scratch("q191_")
    limits = {"sentence_words": {"body": 20}, "paragraph_words": 100}
    write(root / "venue_profiles" / "tven.json", json.dumps({
        "id": "tven", "label": "T Venue",
        "article_types": [{"id": "article", "label": "Article"}],
        "style_limits": limits,
    }))
    snap = {"id": "tven", "label": "T Venue",
            "article_types": [{"id": "article", "label": "Article"}]}
    P._DISPLAY_RULE_INHERIT_CACHE.clear()
    prof = P._snapshot_profile({"venue": "tven", "venue_profile": snap}, "tven", root=root)
    check("F191 the snapshot carries the profile file's style_limits",
          bool(prof) and prof.data.get("style_limits") == limits,
          str(prof.data.get("style_limits") if prof else None))


# ---------------------------------------------------------------------------
# F192
# ---------------------------------------------------------------------------
def test_f192_falsy_blocks_are_rejected() -> None:
    print("\n== F192: falsy non-object blocks are not treated as absent ==")
    base = {"id": "x", "article_types": [{"id": "article", "label": "Article"}]}
    cases = [("prompt", []), ("prompt", ""), ("submission", []),
             ("image_dpi", []), ("image_dpi", False), ("figure_text", ""),
             ("style_limits", []), ("style_limits", False)]
    accepted = []
    for field, value in cases:
        data = dict(base)
        data[field] = value
        try:
            P.normalize_venue_profile(data)
            accepted.append(f"{field}={value!r}")
        except P.VenueProfileError:
            pass
    check("F192 every falsy non-object value is refused", not accepted, str(accepted))
    # An EMPTY OBJECT still means "the profile states no such block".
    try:
        P.normalize_venue_profile(dict(base, image_dpi={}, figure_text={},
                                       style_limits={}, prompt={}, submission={}))
        empty_ok = True
    except P.VenueProfileError:
        empty_ok = False
    check("F192 an empty object still means 'no block'", empty_ok)


# ---------------------------------------------------------------------------
# F193
# ---------------------------------------------------------------------------
def test_f193_venue_level_blocks_apply() -> None:
    print("\n== F193: venue-level captions / cover letter apply next to types ==")
    data = {
        "id": "x",
        "article_types": [{"id": "article", "label": "Article"}],
        "captions": {"published_limit": 200, "default_cap": 200, "source": "top-level"},
        "length_limits": {"cover_letter": {"min": 300, "max": 500,
                                           "source": "top-level"}},
    }
    norm = P.normalize_venue_profile(data)
    check("F193 normalized captions come from the venue-level block",
          norm["captions"].get("default_cap") == 200,
          str(norm["captions"]))
    prof = P.VenueProfile(dict(data))
    check("F193 the venue-level legend policy is enforced",
          prof.captions.get("default_cap") == 200, str(prof.captions))
    cover = prof.length_limits()["cover letter"]
    check("F193 the venue-level cover-letter preference is enforced",
          (cover.get("min"), cover.get("max")) == (300, 500), str(cover))
    # A type's OWN block still wins over the venue-level fallback.
    own = dict(data, article_types=[{
        "id": "article", "label": "Article",
        "captions": {"published_limit": 11, "default_cap": 11, "source": "type"}}])
    check("F193 a type's own caption block still wins",
          P.VenueProfile(own).captions.get("default_cap") == 11)


# ---------------------------------------------------------------------------
# F195
# ---------------------------------------------------------------------------
def test_f195_unreadable_profile_is_reported() -> None:
    print("\n== F195: an unreadable profile file is named when inheritance fails ==")
    root = scratch("q195_")
    write(root / "venue_profiles" / "tven.json", "{bad json")
    snap = {"id": "tven", "label": "T Venue",
            "article_types": [{"id": "article", "label": "Article"}]}
    P._DISPLAY_RULE_INHERIT_CACHE.clear()
    ctx = ctx_for(root, {"venue": "tven", "venue_profile": snap})
    base, err = P.venue_profile_base(ctx)
    check("F195 the valid snapshot still loads", base is not None and err is None, str(err))
    _notes, problems = P.venue_config_findings(ctx)
    check("F195 the lost inheritance is an operator-facing problem",
          any("NOT inherited" in p and "tven.json" in p for p in problems),
          str(problems)[:300])


# ---------------------------------------------------------------------------
# F197
# ---------------------------------------------------------------------------
def _official_tex() -> str:
    return ("\\documentclass{article}\n\\begin{document}\n"
            "\\section{Introduction}\nBody text.\n\\end{document}\n")


def test_f197_malformed_requirements_fail_the_build() -> None:
    print("\n== F197: a malformed official requirements.json fails the build ==")
    root = scratch("q197_")
    (root / "venue_profiles").mkdir(parents=True)
    off = root / "venue_profiles" / "tven.official"
    off.mkdir()
    write(off / "Template.tex", _official_tex())
    write(off / "requirements.json", json.dumps(
        {"mandatory_sections": ["Data availability"]}))
    report = P.build_venue_templates("tven", root=root,
                                     profiles_dir=root / "venue_profiles")
    check("F197 a readable pin reaches the pack",
          "Data availability" in (report.get("mandatory_sections") or []),
          str(report.get("mandatory_sections")))
    write(off / "requirements.json", "{bad json")
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            P.build_venue_templates("tven", root=root,
                                    profiles_dir=root / "venue_profiles")
        refused = False
    except SystemExit as e:
        refused = int(e.code or 0) != 0
    check("F197 an unreadable pin fails instead of dropping its sections", refused)
    check("F197 the failure names requirements.json",
          "requirements.json" in err.getvalue(), err.getvalue()[:200])


# ---------------------------------------------------------------------------
# F198
# ---------------------------------------------------------------------------
def test_f198_malformed_structure_is_reported() -> None:
    print("\n== F198: a malformed pack structure.json is not 'no pack' ==")
    root = scratch("q198_")
    pack = root / "venue_profiles" / "pven.templates"
    pack.mkdir(parents=True)
    write(pack / "venue_architecture.md", "# x\n")
    write(pack / "structure.json", "{bad json")
    raised = False
    try:
        P.official_template_requirements("pven", root=root)
    except P.VenueProfileError as e:
        raised = "structure.json" in str(e)
    check("F198 an unreadable structure.json is reported, not read as no pack", raised)
    write(pack / "structure.json", json.dumps(
        {"official": {"mandatory_sections": ["Results"]}, "norm": {}}))
    req = P.official_template_requirements("pven", root=root)
    check("F198 a readable pack still yields its requirements",
          req.get("mandatory_sections") == ["Results"], str(req))


# ---------------------------------------------------------------------------
# F199
# ---------------------------------------------------------------------------
CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
</w:styles>"""


def _para(style, text):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _docx(path: Path, body: str) -> None:
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           "<w:body>" + body + "<w:sectPr/></w:body></w:document>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", xml)
        z.writestr("word/styles.xml", STYLES)


def test_f199_docx_prose_is_not_a_section() -> None:
    print("\n== F199: a DOCX body paragraph cannot satisfy a mandatory section ==")
    prose = scratch("q199_prose_")
    _docx(prose / "paper.docx", _para("Heading1", "Introduction")
          + _para(None, "Results"))
    rep = P.scan_template_conformance([(prose, "", ())],
                                      {"mandatory_sections": ["Results"]})
    check("F199 plain prose 'Results' does not satisfy the section",
          rep["missing_sections"] == ["Results"] and rep["conforms"] is False,
          str(rep["missing_sections"]))
    heading = scratch("q199_heading_")
    _docx(heading / "paper.docx", _para("Heading1", "Introduction")
          + _para("Heading1", "Results"))
    rep2 = P.scan_template_conformance([(heading, "", ())],
                                       {"mandatory_sections": ["Results"]})
    check("F199 a real Heading1 'Results' still satisfies it",
          rep2["missing_sections"] == [], str(rep2["missing_sections"]))


# ---------------------------------------------------------------------------
# F200
# ---------------------------------------------------------------------------
def test_f200_no_dangling_paged_pointer() -> None:
    print("\n== F200: nothing paged means no pointer and no missing file ==")
    sb = scratch("q200_")
    prompt = P.page_stage_prompt(sb, "TASK BODY", [], "judge", "medium")
    check("F200 the prompt never names the paged file",
          "INSTRUCTIONS/PROFILE_RULES.md" not in prompt,
          prompt[:200])
    check("F200 no PROFILE_RULES.md is written", not (sb / "INSTRUCTIONS" /
                                                       "PROFILE_RULES.md").exists())
    check("F200 the capacity contract and postcheck bindings remain",
          prompt.lstrip().startswith("=== EXECUTION PROFILE: medium")
          and "THE POSTCHECKS ARE UNCHANGED" in prompt)
    sb2 = scratch("q200_ok_")
    prompt2 = P.page_stage_prompt(sb2, "BODY\nRULE TEXT", [("R", "RULE TEXT")],
                                  "judge", "medium")
    paged = sb2 / "INSTRUCTIONS" / "PROFILE_RULES.md"
    check("F200 a real paged section still writes the file and keeps its pointer",
          paged.is_file() and "INSTRUCTIONS/PROFILE_RULES.md" in prompt2
          and "## R" in paged.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# F201
# ---------------------------------------------------------------------------
def test_f201_duplicate_titles_get_unique_sections() -> None:
    print("\n== F201: duplicate block titles stay distinct and in prompt order ==")
    sb = scratch("q201_")
    prompt = P.page_stage_prompt(
        sb, "HEAD\nSHORT RULE\nLONGER RULE TEXT\nTAIL",
        [("SAME", "SHORT RULE"), ("SAME", "LONGER RULE TEXT")], "judge", "medium")
    paged = (sb / "INSTRUCTIONS" / "PROFILE_RULES.md").read_text(encoding="utf-8")
    titles = re.findall(r"section `([^`]+)`", prompt)
    check("F201 the two pointers name distinct sections",
          len(titles) == 2 and titles[0] != titles[1], str(titles))
    check("F201 the paged file carries both sections in prompt order",
          paged.find("SHORT RULE") < paged.find("LONGER RULE TEXT"),
          paged[paged.find("## SAME"):].replace("\n", " | ")[:160])
    check("F201 each heading matches one pointer", titles == re.findall(
        r"(?m)^## (.+)$", paged), str(titles))


# ---------------------------------------------------------------------------
# F203
# ---------------------------------------------------------------------------
def test_f203_findings_md_lists_the_rows() -> None:
    print("\n== F203: the synthesized findings.md lists its X-9xx rows ==")
    sb = scratch("q203_")
    ctx = ctx_for(sb, {"journal_mode": "off", "venue": "generic"})
    real = P.cold_start_findings_rows
    P.cold_start_findings_rows = lambda c, r: [
        {"id": "X-901", "title": "A frozen row from the probe"}]
    try:
        P.synthesize_frozen_review(ctx, 1, sb)
    finally:
        P.cold_start_findings_rows = real
    md = (sb / "guided_review" / "findings.md").read_text(encoding="utf-8")
    check("F203 the row id is written below the count sentence",
          "X-901" in md and "A frozen row from the probe" in md, md[-200:])


def main() -> int:
    tests = (test_f190_invalid_snapshot_is_reported,
             test_f191_snapshot_inherits_style_limits,
             test_f192_falsy_blocks_are_rejected,
             test_f193_venue_level_blocks_apply,
             test_f195_unreadable_profile_is_reported,
             test_f197_malformed_requirements_fail_the_build,
             test_f198_malformed_structure_is_reported,
             test_f199_docx_prose_is_not_a_section,
             test_f200_no_dangling_paged_pointer,
             test_f201_duplicate_titles_get_unique_sections,
             test_f203_findings_md_lists_the_rows)
    try:
        for fn in tests:
            fn()
    finally:
        for tmp in TMPDIRS:
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL FIX-BUGS Q CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

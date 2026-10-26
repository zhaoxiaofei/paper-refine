#!/usr/bin/env python3
"""Regression checks for the 2026-10-27 fix-bugs wave 1.

Run:  python3 .paper_test/test_fix_bugs_20261027_wave1.py

The findings were verified by two independent passes over the 2026-10-27
find-bugs tree. Every check here fails on the pre-fix tree and pins the
smallest observed defect.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1027_pp", "paper_pipeline.py")
pf = load("fixbugs1027_pf", "paper_docx_format.py")
cw = load("fixbugs1027_cw", "paper-skills/paper-review/scripts/count_words.py")
ec = load("fixbugs1027_ec", "paper-skills/paper-review/scripts/extract_citations.py")
en = load("fixbugs1027_en", "paper-skills/paper-review/scripts/extract_numbers.py")
ea = load("fixbugs1027_ea", "paper-skills/paper-review/scripts/extract_acronyms.py")
eo = load("fixbugs1027_eo", "paper-skills/paper-review/scripts/extract_occurrences.py")

FAILS = []
TMPDIRS = []


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def run(argv, **kw):
    return subprocess.run([sys.executable] + [str(a) for a in argv],
                          capture_output=True, text=True, **kw)


def test_candidate_extractors():
    print()
    print("== extractors: F31-F39 ==")
    auc = dict(en.LABEL_PATTERNS)["AUC"]
    check("F31 an AUC at the end of a sentence is enumerated",
          bool(auc.search("The AUC was 0.81.")) and auc.search("The AUC was 0.81.5") is None,
          str(auc.search("The AUC was 0.81.")))
    lines, _captions, _abstract = cw.tex_lines(
        "% \\begin{verbatim}\nReal prose words here.\n")
    check("F32 a commented-out \\begin{verbatim} does not blank the rest",
          any("Real prose" in ln for ln in lines), str(lines))
    tex = ec.latex_source_text("% \\begin{verbatim}\n\\cite{real}\n")
    check("F33 a commented-out verbatim fence does not hide real citations",
          "\\cite{real}" in tex and len(ec.TEX_CITE_RE.findall(tex)) == 1, tex)
    check("F34 a numbered References heading is found",
          bool(ec.REF_HEAD_RE.match("7. References"))
          and bool(en.REF_HEAD_RE.match("7. References"))
          and bool(ea.REF_HEADING_RE.match("7. References")))
    check("F36 \\citestyle/\\citetext are not citation call-outs",
          not ec.TEX_CITE_RE.search("\\citestyle{nature}")
          and not ec.TEX_CITE_RE.search("\\citetext{see}")
          and bool(ec.TEX_CITE_RE.search("\\citep[see][p. 2]{a,b}")))
    pat5 = eo.variant_pattern("5", "value")
    pat234 = eo.variant_pattern("234", "value")
    check("F35 value mode rejects a sign and a thousands separator",
          pat5.findall("5 mg -5 mg \u22125 mg +5 mg") == ["5"]
          and pat234.findall("1,234 cells and 234 cells") == ["234"])
    check("F35 a thousands value does not gain a decimal spelling",
          not eo.variant_pattern("1,234", "value").search("1.234 cells"))
    # F38: a legal id-less article type, read exactly as the pipeline does.
    tmp = scratch("fixbugs1027_type_")
    profile = tmp / "p.json"
    profile.write_text(json.dumps({"id": "v", "article_types": [
        {"label": "Brief Communication", "length_limits": {
            "abstract": {"base": 100, "relaxation": 1.1},
            "main_text": {"base": 1000, "relaxation": 1.25}}}]}), encoding="utf-8")
    ms = tmp / "ms.md"
    ms.write_text("Abstract\n\nA short abstract.\n", encoding="utf-8")
    proc = run([WS / "paper-skills/paper-review/scripts/count_words.py",
                "--venue-profile", profile, "--article-type", "brief-communication", "--json", ms])
    check("F38 an id-less article type resolves from its label",
          proc.returncode == 0 and '"abstract": 110' in proc.stdout,
          proc.stdout + proc.stderr)
    # F39: comments are not prose for the acronym/number sweeps.
    work = tmp / "work"
    (work / "corpus").mkdir(parents=True)
    (work / "corpus" / "main.tex.txt").write_text(
        "Results: p = 0.03, FACS sorting worked.\n"
        "% Old text mentioned scRNA-seq and p = 0.001.\n", encoding="utf-8")
    run([WS / "paper-skills/paper-review/scripts/extract_numbers.py", "--work", work,
         "--out", work])
    run([WS / "paper-skills/paper-review/scripts/extract_acronyms.py", "--work", work,
         "--out", work])
    m4 = json.loads((work / "artifacts" / "M4_numbers.json").read_text(encoding="utf-8"))
    m1 = json.loads((work / "artifacts" / "M1_acronyms.json").read_text(encoding="utf-8"))
    labels = {(r.get("label"), r.get("value")) for r in m4.get("metrics") or []}
    tokens = {r.get("acronym") for r in m1 if isinstance(r, dict)}
    check("F39 comments do not feed the number/acronym sweeps",
          ("p-value", "0.03") in labels and ("p-value", "0.001") not in labels
          and "FACS" in tokens and "scRNA" not in tokens,
          f"{labels} {tokens}")


def test_docx_fixes():
    print()
    print("== DOCX: F19/F22/F24/F25/F29 ==")
    import xml.etree.ElementTree as ET
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    para = ('<w:p><w:r><w:t>alpha</w:t><w:noBreakHyphen/>'
            '<w:sym w:font="Symbol" w:char="F0B1"/><w:t>beta</w:t></w:r></w:p>')
    new, applied = pf.rewrite_text_spans(para, [(0, 5, "ALPHA")])
    try:
        ET.fromstring(f"<w:body {ns}>{new}</w:body>")
        wellformed = True
    except ET.ParseError:
        wellformed = False
    check("F19 an edit beside noBreakHyphen/sym stays well-formed",
          wellformed and "w:noBreakHyphen" in new and "w:sym" in new
          and "ALPHA" in pf.text_of(new), new)
    paragraphs = [
        (0, 0, '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
               '<w:r><w:t>Head</w:t></w:r></w:p>'),
        (100, 100, '<w:p><w:r><w:footnoteReference w:id="1"/></w:r></w:p>'),
    ]
    groups, _prescribed = pf.stray_empty_paragraph_groups(
        paragraphs, {"max_empty_paragraph_run": 1, "empty_paragraph_slots": []})
    check("F22 a paragraph carrying only a footnote anchor is not stray-empty",
          groups == [], str(groups))
    check("F24 a title run carrying volume/pages/year is not title-only",
          not pf._title_only("Nature Methods 11, 1-2 (2024)", "Nature Methods")
          and pf._title_only("Nature Methods.", "Nature Methods"))
    masked = pf.spelling_nonprose_mask(
        "https://example.org/colour-chart `colour` colour")
    check("F25 a URL's spelling is not a spelling target and is not rewritten",
          pf.spelling_minority_targets(["https://example.org/colour-chart"]) == {}
          and "colour-chart" not in masked and "`colour`" not in masked
          and masked.rstrip().endswith("colour"), masked)
    rpr = ('<w:rPr><w:i w:val="0"/><w:rPrChange w:id="1" w:author="x">'
           '<w:rPr><w:i/></w:rPr></w:rPrChange></w:rPr>')
    check("F29 live emphasis ignores the rPrChange revision record",
          pf.effective_emphasis({}, "Normal", None, rpr) is False
          and pf.live_rpr(rpr) == '<w:rPr><w:i w:val="0"/></w:rPr>')
    simple = ('<w:p><w:fldSimple w:instr=" ADDIN ZOTERO_ITEM ">'
              '<w:r><w:t>[1]</w:t></w:r></w:fldSimple>'
              '<w:r><w:t> colour</w:t></w:r></w:p>')
    ranges = pf.field_result_text_ranges(simple)
    check("F28 a w:fldSimple result is protected from a text edit",
          ranges and pf.in_field_result(ranges, 0, 3), str(ranges))
    check("F20 a PAGE field is not flattened by the Zotero unlink",
          "PAGE" in pf._unlink_fields(
              '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText> PAGE </w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              '<w:r><w:t>7</w:t></w:r>'
              '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')[0])


def test_documentation_consistency():
    print()
    print("== docs: F15/F16/F17 ==")
    readme = (WS / "README.md").read_text(encoding="utf-8")
    test_readme = (WS / ".paper_test" / "README.md").read_text(encoding="utf-8")
    fcv = (WS / ".paper_test" / "test_final_clean_version.py").read_text(encoding="utf-8")
    check("F15 README no longer claims the removed `none` alias is accepted",
          "still accepted as an alias" not in readme
          and "`set-revision-mode none` is removed" in readme)
    check("F16 the test README documents `--author-to-complete`, not the removed aliases",
          "`--author-to-complete readme|document|off`" in test_readme
          and "the default is `--with-author-to-complete-in-readme`" not in test_readme)
    check("F17 the final-clean docs describe pin-identical names, not an increment",
          "generation counter +1" not in fcv
          and "byte-identical to the judged champion" in fcv
          and "generation counter INCREMENTED" not in test_readme)


def test_pipeline_fixes():
    print()
    print("== pipeline: F13/F43/F53/F58/F59/F61 ==")
    spec = pp.parse_only_spec("r2_r1_w2_j1")
    check("F43 a documented lead-pin judge selector parses",
          spec is not None and spec.rounds == {2}
          and spec.judge_spec_for(2) == "r2_r1_w2_j1",
          str(getattr(spec, "judge_selectors", None)))
    reason = pp.final_clean_reason({"round": 1}, [{"round": 1, "mismatch": None}], 1, None,
                                   True, False, {}, [], skipped="the champion corpus is empty")
    check("F58 a skipped final_clean_version is a certification blocker",
          "not published" in reason and "empty" in reason, reason)
    root = scratch("fixbugs1027_root_") / "root"
    src = root.parent / "src"
    src.mkdir(parents=True)
    (src / "ms.md").write_text("Abstract\n\nA short abstract.\n", encoding="utf-8")
    proc = run([WS / "paper_pipeline.py", "setup", "--source", src, "--root", root,
                "--rounds", "1", "--rewrites", "0", "--revises", "1", "--judges", "1",
                "--revision-audit", "off"])
    check("F13 the setup root is created", proc.returncode == 0, proc.stderr[-300:])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("F13 an explicit revision_audit=off is stored", cfg.get("revision_audit") == "off")
    proc = run([WS / "paper_pipeline.py", "set-revision-mode", "--root", root, "major",
                "--force"])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("F59 a scoped mode turns the probe off",
          proc.returncode == 0 and cfg.get("probe_review") == "off"
          and cfg.get("revision_audit") == "off",
          json.dumps({k: cfg.get(k) for k in ("probe_review", "revision_audit")}))
    proc = run([WS / "paper_pipeline.py", "set-revision-mode", "--root", root, "continue",
                "--force"])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("F13/F59 leaving a scoped mode restores the operator's audit and probe policies",
          proc.returncode == 0 and cfg.get("revision_audit") == "off"
          and cfg.get("probe_review") == "on",
          json.dumps({k: cfg.get(k) for k in ("probe_review", "revision_audit")}))
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("F52 setup records the operator source manifest before normalization",
          isinstance(state.get("source_manifest_raw"), dict) and state["source_manifest_raw"])
    ctx = pp.Ctx(root)
    ctx.load()
    seeded = root / "seeded_policy"
    seeded.mkdir()
    pp.seed_format_policy_file(ctx, seeded)
    policy = json.loads((seeded / "format_policy.json").read_text(encoding="utf-8"))
    check("F41 the seeded session policy carries the venue DPI/figure-text rules",
          "figure_text" in policy and "image_dpi" in policy
          and "min_image_dpi" in policy, sorted(policy)[:12])
    check("F42 a judge view excludes author READMEs and platform junk",
          pp._is_view_excluded_file("README.md")
          and pp._is_view_excluded_file("paper.pyc")
          and not pp._is_view_excluded_file("main.docx"))
    empty_review = root / "empty_review"
    (empty_review / "artifacts").mkdir(parents=True)
    missing = pp.artifact_quality_report(empty_review, require_files=True)
    check("F44 a deleted decision artifact is a postcheck problem",
          "artifacts/M20_formatting.md" in missing, sorted(missing)[:4])
    proc = run([WS / "paper_pipeline.py", "prune", "--root", root, "--keep-latest", "-1"])
    check("F53 a negative --keep-latest is refused", proc.returncode != 0
          and "keep-latest" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr)
    # F61: --force may replace a built package, never an arbitrary directory.
    dest = root.parent / "not_a_package"
    dest.mkdir()
    (dest / "precious.txt").write_text("keep me\n", encoding="utf-8")
    empty_src = root.parent / "empty_src"
    empty_src.mkdir()
    rep = pp.rebuild_package_from_templates({"t": "x"}, empty_src, dest, force=True)
    check("F61 --force refuses to delete a directory that is not a package",
          rep.get("ok") is False and (dest / "precious.txt").is_file(), str(rep))
    # The confirmed repro: the root carries package documents (a winner, the
    # source corpus), so the ".docx present" test alone still deleted it.
    (root / "round1_winner").mkdir(exist_ok=True)
    (root / "round1_winner" / "ms.docx").write_bytes(b"PK\x03\x04")
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    rep = pp.rebuild_package_from_templates({"t": "x"}, empty_src, root, force=True,
                                            protected=(root,))
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    check("F61 --force refuses the pipeline root itself as a destination",
          rep.get("ok") is False and before == after, str(rep))
    # F62: an external letter is frozen into the root and stored root-relative.
    ext = root.parent / "decision.txt"
    ext.write_text("please revise\n", encoding="utf-8")
    rel = pp._freeze_journal_feedback(root, ext)
    check("F62 an external journal letter is frozen inside the root",
          not Path(rel).is_absolute() and (root / rel).is_file(), rel)


def main() -> int:
    try:
        test_candidate_extractors()
        test_docx_fixes()
        test_documentation_consistency()
        test_pipeline_fixes()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): " + ", ".join(FAILS))
        return 1
    print("ALL 2026-10-27 WAVE-1 FIX CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regression checks for the 2026-11-15 fix-bugs wave 2, group `venues`.

Each check pins one candidate (F66-F78) this wave re-validated on the tree and
repaired in `paper_pipeline_parts/p01_venues.py` (+ the `recent-practice`
sentence in `venue_profiles/README.md`). Hermetic: every fixture lives under
`tempfile.mkdtemp()` and the venue functions are called directly with small
dicts/files.

Run:  python3 .paper_test/test_fix_bugs_20261115_wave2_venues.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
spec = importlib.util.spec_from_file_location("fb1115w2_venues_pp",
                                             str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(spec)
sys.modules["fb1115w2_venues_pp"] = pp
spec.loader.exec_module(pp)

TMPDIRS = []
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def quiet(fn, *args, **kwargs):
    """Run a `die()`-style call, returning (result, SystemExit|None, stderr)."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return fn(*args, **kwargs), None, err.getvalue()
    except SystemExit as exc:
        return None, exc, err.getvalue()


def section(title):
    print(f"\n== {title} ==")


# ---------------------------------------------------------------------------
# F66 -- no section evidence means no invented IMRAD architecture
# ---------------------------------------------------------------------------
def test_f66() -> None:
    section("F66: the skeleton never invents an IMRAD order")
    check("F66 with no norm and no official tier the skeleton has no sections",
          pp._skeleton_titles({}, {}) == [], pp._skeleton_titles({}, {}))
    check("F66 the same holds for an official pack that parsed no section",
          pp._skeleton_titles({}, {"sections": [], "mandatory_sections": []}) == [])
    word = pp.render_word_template("v", {}, {"sections": [], "mandatory_sections": []})
    check("F66 the word template says there is no section evidence",
          "No section evidence" in word and "## Results" not in word
          and "## Discussion" not in word, word[:400])
    latex = pp.render_latex_template("v", {}, {"sections": [], "mandatory_sections": []})
    check("F66 the LaTeX template says there is no section evidence",
          "No section evidence" in latex and "\\section{Results}" not in latex
          and "\\section{Discussion}" not in latex, latex[:400])

    # End to end: a template file that carries a title but no body heading.
    root = scratch("fb1115w2_f66_")
    pdir = root / "venue_profiles"
    off = pdir / "v.official"
    off.mkdir(parents=True)
    (off / "Sample_Template.md").write_text("# <Title>\n\n<Body text, no headings.>\n")
    res = pp.build_venue_templates("v", profiles_dir=pdir)
    word = (pdir / "v.templates" / "word-template.md").read_text()
    check("F66 a section-less official template yields no fabricated skeleton sections",
          res["norm_sections"] == [] and "## Results" not in word
          and "## Introduction" not in word, repr(res["norm_sections"]))


# ---------------------------------------------------------------------------
# F67 -- a supplementary official template must not veto mandatory sections
# ---------------------------------------------------------------------------
def test_f67() -> None:
    section("F67: official sample roles drive the mandatory-section set")
    body = ["Abstract", "Introduction", "Methods", "Results", "Discussion"]

    def rec(name, title_list, role):
        return {"file": name, "sha256": "x" * 8, "format": "md", "role": role,
                "sections": [{"level": 1, "title": t} for t in title_list],
                "statements": []}

    main = rec("Main_Template.md", body, "main")
    off = pp.official_skeleton([main, dict(main, file="Main_Template_2.md"),
                                rec("Supplementary_Template.md",
                                    ["Supplementary Results", "Appendix"], "supp")])
    check("F67 the main templates' shared sections stay mandatory",
          off["mandatory_sections"] == body, off["mandatory_sections"])
    check("F67 the supplement heading is not mandatory",
          "Supplementary Results" not in off["mandatory_sections"])

    # The pre-F67 shape (a record with no role) still behaves as a main sample.
    legacy = [{"file": "a.md", "sha256": "y", "sections":
               [{"level": 1, "title": t} for t in body]},
              {"file": "b.md", "sha256": "z", "sections":
               [{"level": 1, "title": t} for t in body]}]
    check("F67 records without a role are main samples",
          pp.official_skeleton(legacy)["mandatory_sections"] == body,
          pp.official_skeleton(legacy)["mandatory_sections"])


# ---------------------------------------------------------------------------
# F68 -- a pinned mandatory section is in the generated skeleton
# ---------------------------------------------------------------------------
def test_f68() -> None:
    section("F68: an operator-pinned mandatory section reaches the skeleton")
    official = {"sections": [{"level": 1, "title": "Abstract", "mean_position": 0},
                             {"level": 1, "title": "Methods", "mean_position": 1}],
                "mandatory_sections": ["Abstract", "Methods", "Data availability"]}
    titles = pp._skeleton_titles({}, official)
    check("F68 the pinned section is appended to the skeleton",
          titles == ["Abstract", "Methods", "Data availability"], titles)
    word = pp.render_word_template("v", {}, official)
    check("F68 the pinned section is marked [MANDATORY] in the word template",
          "## Data availability [MANDATORY]" in word, word[:500])
    check("F68 a pinned-only requirement still gets the mandatory note",
          "marked [MANDATORY]" in word)
    latex = pp.render_latex_template("v", {}, official)
    check("F68 the pinned section is in the LaTeX skeleton too",
          "\\section{Data availability}" in latex, latex[:400])
    # No duplicate when the pin names a section the official tier already carries.
    check("F68 an already-present pinned section is not duplicated",
          pp._skeleton_titles({}, official).count("Methods") == 1)


# ---------------------------------------------------------------------------
# F69 -- requirements.json is shape-validated
# ---------------------------------------------------------------------------
def test_f69() -> None:
    section("F69: a requirements.json of the wrong shape fails the build")
    base = scratch("fb1115w2_f69_")
    for payload in (["Data availability"],
                    {"mandatory_sections": "Data availability"},
                    {"mandatory_sections": ["", "Methods"]},
                    {"mandatory_sections": [2]}):
        root = scratch("fb1115w2_f69_case_")
        pdir = root / "venue_profiles"
        off = pdir / "v.official"
        off.mkdir(parents=True)
        (off / "Main_Template.md").write_text("# Title\n\n## Methods\n\nm\n")
        (off / "requirements.json").write_text(json.dumps(payload))
        res, exc, err = quiet(pp.build_venue_templates, "v", profiles_dir=pdir)
        check(f"F69 {payload!r} is refused, not read", exc is not None,
              f"res={res!r}")
        check(f"F69 {payload!r} names the file", "requirements.json" in err, err[:300])
        check(f"F69 {payload!r} installs no pack",
              not (pdir / "v.templates" / "structure.json").is_file())

    good, exc, _ = quiet(pp._validated_explicit_requirements,
                         {"mandatory_sections": [" Data availability "]}, "x.json")
    check("F69 a well-shaped pin is trimmed and kept",
          exc is None and good["mandatory_sections"] == ["Data availability"], good)
    check("F69 no pin reads as no requirements",
          pp._validated_explicit_requirements(None, "x.json") == {})
    check("F69 an unexpected extra key is preserved",
          pp._validated_explicit_requirements({"note": "n"}, "x.json")["note"] == "n")


# ---------------------------------------------------------------------------
# F70 -- structure.json's official block is shape-validated
# ---------------------------------------------------------------------------
def test_f70() -> None:
    section("F70: the pack's official block is shape-checked, naming the field")
    cases = [
        ({"mandatory_sections": "Data availability"}, "mandatory_sections"),
        ({"mandatory_sections": ["Methods", 3]}, "mandatory_sections"),
        ({"statements": ["Data availability"]}, "statements"),
        ({"statements": [{"present": 1}]}, "statements"),
        ({"sections": "Methods"}, "sections"),
        ({"sections": [{"level": 1}]}, "sections"),
    ]
    for bad, field in cases:
        root = scratch("fb1115w2_f70_")
        pack = root / "venue_profiles" / "v.templates"
        pack.mkdir(parents=True)
        (pack / "venue_architecture.md").write_text("x\n")
        official = {"sections": [{"level": 1, "title": "Methods"}],
                    "mandatory_sections": ["Methods"], "statements": []}
        official.update(bad)
        (pack / "structure.json").write_text(json.dumps(
            {"venue": "v", "official": official, "norm": {"sections": []}}))
        try:
            pp.official_template_requirements("v", root=root)
            err = ""
        except pp.VenueProfileError as exc:
            err = str(exc)
        check(f"F70 {bad!r} is a named broken pack", field in err and "structure.json" in err,
              err[:300])

    root = scratch("fb1115w2_f70_ok_")
    pack = root / "venue_profiles" / "v.templates"
    pack.mkdir(parents=True)
    (pack / "venue_architecture.md").write_text("x\n")
    (pack / "structure.json").write_text(json.dumps({
        "venue": "v",
        "official": {"sections": [{"level": 1, "title": "Methods"}],
                     "mandatory_sections": ["Methods"],
                     "statements": [{"label": "Data availability"}]},
        "norm": {"sections": [{"title": "Results", "mean_position": 2}]}}))
    req = pp.official_template_requirements("v", root=root)
    check("F70 a well-shaped pack still resolves",
          req.get("mandatory_sections") == ["Methods"]
          and req.get("advisory_sections") == ["Results"], req)


# ---------------------------------------------------------------------------
# F71 -- numbered headings enter the architecture-order check
# ---------------------------------------------------------------------------
def test_f71() -> None:
    section("F71: numbered headings are order-checked")
    req = {"official": True,
           "sections": [{"level": 1, "title": "Abstract"},
                        {"level": 1, "title": "Methods"},
                        {"level": 1, "title": "Results"}]}
    root = scratch("fb1115w2_f71_")
    src = root / "src"
    src.mkdir()
    (src / "paper.md").write_text(
        "# Title\n\n## 1. Abstract\n\nx\n\n## 2. Results\n\nz\n\n## 3. Methods\n\ny\n")
    res = pp.scan_template_conformance([(src, "", ())], req)
    check("F71 an out-of-order numbered manuscript is reported",
          any("Methods" in r and "Results" in r for r in res["order_rows"]),
          res["order_rows"])
    check("F71 that scan does not conform", res["conforms"] is False)
    (src / "paper.md").write_text(
        "# Title\n\n## 1. Abstract\n\nx\n\n## 2. Methods\n\ny\n\n## 3. Results\n\nz\n")
    res = pp.scan_template_conformance([(src, "", ())], req)
    check("F71 a correctly ordered numbered manuscript has no order row",
          res["order_rows"] == [], res["order_rows"])
    # A numbered requirement title is matched too.
    req_num = {"official": True,
               "sections": [{"level": 1, "title": "1. Abstract"},
                            {"level": 1, "title": "2. Methods"}]}
    res = pp.scan_template_conformance([(src, "", ())], req_num)
    check("F71 numbered requirement titles match unnumbered headings",
          res["order_rows"] == [], res["order_rows"])


# ---------------------------------------------------------------------------
# F72 -- prose mentions are not captions
# ---------------------------------------------------------------------------
def test_f72() -> None:
    section("F72: 'Figure 2 shows ...' prose is not a caption")
    root = scratch("fb1115w2_f72_")
    src = root / "src"
    src.mkdir()
    (src / "paper.md").write_text(
        "# Title\n\n## Methods\n\nm\n\n"
        "Figure 2 shows the main result.\n\nTable 1 shows the demographics.\n")
    req = {"official": True, "sections": [{"level": 1, "title": "Methods"}],
           "mandatory_sections": ["Methods"]}
    res = pp.scan_template_conformance([(src, "", ())], req)
    check("F72 prose mentions produce no numbering row", res["label_rows"] == [],
          res["label_rows"])
    check("F72 the prose-only corpus conforms", res["conforms"] is True)
    (src / "paper.md").write_text(
        "# Title\n\n## Methods\n\nm\n\nFigure 1. First.\n\nFigure 3. Third.\n")
    res = pp.scan_template_conformance([(src, "", ())], req)
    check("F72 a genuine caption gap is still reported",
          any("gaps" in r and "[2]" in r for r in res["label_rows"]), res["label_rows"])
    (src / "paper.md").write_text(
        "# Title\n\n## Methods\n\nm\n\nFigure 2. Second.\n\nFigure 1. First.\n")
    res = pp.scan_template_conformance([(src, "", ())], req)
    check("F72 a genuine caption-order defect is still reported",
          any("out of order" in r for r in res["label_rows"]), res["label_rows"])


# ---------------------------------------------------------------------------
# F73 -- a cover letter is not the manuscript
# ---------------------------------------------------------------------------
def test_f73() -> None:
    section("F73: a cover letter cannot satisfy manuscript requirements")
    root = scratch("fb1115w2_f73_")
    src = root / "src"
    src.mkdir()
    (src / "manuscript.md").write_text("# Title\n\n## Introduction\n\nx\n")
    (src / "cover_letter.md").write_text(
        "# Cover letter\n\n## Methods\n\nWe used Methods.\n\n"
        "Data availability: all data are available.\n")
    req = {"official": True, "sections": [{"level": 1, "title": "Methods"}],
           "mandatory_sections": ["Methods"],
           "statements": [{"label": "Data availability"}]}
    res = pp.scan_template_conformance([(src, "", ())], req)
    check("F73 the letter's heading does not satisfy the mandatory section",
          res["missing_sections"] == ["Methods"], res["missing_sections"])
    check("F73 the letter's sentence does not satisfy the statement",
          res["missing_statements"] == ["Data availability"], res["missing_statements"])
    check("F73 the scan does not conform", res["conforms"] is False)
    check("F73 the letter is not counted as a manuscript document",
          res["found"]["documents"] == ["manuscript.md"], res["found"]["documents"])

    # The article-type manuscript rule still wins: a Letter-to-the-Editor run's
    # OWN manuscript is a main document, not a cover letter.
    type_src = root / "letters"
    type_src.mkdir()
    (type_src / "letter-to-the-editor.md").write_text("# Title\n\n## Methods\n\nm\n")
    res = pp.scan_template_conformance([(type_src, "", ())], req,
                                       manuscript_names=["letter to the editor"])
    check("F73 a type-named manuscript is still a main document",
          res["missing_sections"] == [], res["missing_sections"])


# ---------------------------------------------------------------------------
# F74 -- unreadable DOCX / template is reported, not silently skipped
# ---------------------------------------------------------------------------
def test_f74() -> None:
    section("F74: an unreadable document or template is a reported gap")
    root = scratch("fb1115w2_f74_")
    src = root / "src"
    src.mkdir()
    (src / "broken.docx").write_bytes(b"not a zip at all")
    req = {"official": True, "sections": [{"level": 1, "title": "Methods"}],
           "mandatory_sections": ["Methods"]}
    res = pp.scan_template_conformance([(src, "", ())], req)
    check("F74 an unreadable DOCX is listed in unparsed",
          res["unparsed"] == ["broken.docx"], res["unparsed"])
    check("F74 an unreadable document means the corpus does not conform",
          res["conforms"] is False)

    tpl = src / "template.docx"
    tpl.write_bytes(b"corrupt template")
    res = pp.scan_template_conformance([(src, "", ())],
                                       {"official": True, "sections": [],
                                        "mandatory_sections": []},
                                       word_template=tpl)
    check("F74 an unreadable governing template is an unanswered requirement",
          res["word_template_rows"] and "template.docx" in res["word_template_rows"][0],
          res["word_template_rows"])
    check("F74 word_template_ok is False for an unreadable template",
          res["word_template_ok"] is False)


# ---------------------------------------------------------------------------
# F75 -- figure numbering is per submission unit, not per corpus
# ---------------------------------------------------------------------------
def test_f75() -> None:
    section("F75: a supplement's own numbering is its own sequence")
    root = scratch("fb1115w2_f75_")
    src = root / "src"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "# Title\n\n## Methods\n\nm\n\nFigure 2. Second.\n\nFigure 3. Third.\n")
    (src / "supplement.md").write_text(
        "# Supplementary\n\n## Supplementary Methods\n\nsm\n\nFigure 1. Supp first.\n")
    req = {"official": True, "sections": [{"level": 1, "title": "Methods"}]}
    res = pp.scan_template_conformance([(src, "", ())], req)
    check("F75 the supplement does not make the main sequence out of order",
          not any("out of order" in r for r in res["label_rows"]), res["label_rows"])
    check("F75 the supplement is never charged to the main sequence",
          not any("supplement" in r for r in res["label_rows"]), res["label_rows"])
    check("F75 a real main-sequence gap is still reported",
          any("gaps" in r and "[1]" in r for r in res["label_rows"]), res["label_rows"])

    (src / "manuscript.md").write_text(
        "# Title\n\n## Methods\n\nm\n\nFigure 1. First.\n\nFigure 2. Second.\n")
    (src / "supplement.md").write_text(
        "# Supplementary\n\n## Supplementary Methods\n\nsm\n\nFigure 1. Supp.\n")
    res = pp.scan_template_conformance([(src, "", ())], req)
    check("F75 a clean main + restarting supplement yields no row",
          res["label_rows"] == [], res["label_rows"])


# ---------------------------------------------------------------------------
# F76 -- the advisory norm de-duplicates a repeated heading per exemplar
# ---------------------------------------------------------------------------
def test_f76() -> None:
    section("F76: one exemplar cannot present a section twice")
    recs = [{"file": "a.md", "format": "md", "sections": [
        {"level": 1, "title": "Introduction"},
        {"level": 1, "title": "Results"},
        {"level": 1, "title": "Discussion"},
        {"level": 1, "title": "Results"}]}]
    norm = pp.structure_norm(recs)
    by = {s["title"]: s for s in norm["sections"]}
    check("F76 a repeated heading counts once", by["Results"]["present"] == 1,
          by["Results"])
    check("F76 presence never exceeds the exemplar count",
          all(s["present"] <= norm["n_exemplars"] for s in norm["sections"]))
    check("F76 the repeated heading keeps its FIRST position",
          by["Results"]["mean_position"] == 1.0, by["Results"]["mean_position"])
    check("F76 the advisory order is not inverted by the repeat",
          [s["title"] for s in norm["sections"]] == ["Introduction", "Results", "Discussion"],
          [s["title"] for s in norm["sections"]])
    # Across two exemplars the counts still add up.
    norm2 = pp.structure_norm(recs + [{"file": "b.md", "format": "md", "sections": [
        {"level": 1, "title": "Introduction"},
        {"level": 1, "title": "Results"}]}])
    by2 = {s["title"]: s for s in norm2["sections"]}
    check("F76 two exemplars report 2/2 for a shared section",
          by2["Results"]["present"] == 2 and by2["Results"]["n_exemplars"] == 2, by2["Results"])


# ---------------------------------------------------------------------------
# F78 -- the venue id is validated before it is joined into a path
# ---------------------------------------------------------------------------
def test_f78() -> None:
    section("F78: an unvalidated venue id cannot escape the profile store")
    root = scratch("fb1115w2_f78_")
    pdir = root / "venue_profiles"
    (pdir / "v.manuscripts").mkdir(parents=True)
    (pdir / "v.manuscripts" / "a.md").write_text("# T\n\n## Abstract\n\nx\n")
    (root / "evil.manuscripts").mkdir()
    (root / "evil.manuscripts" / "a.md").write_text("# T\n\n## Secret\n\nx\n")

    for fn, args in ((pp.venue_exemplar_dirs, ("../evil",)),
                     (pp.venue_pack_dir, ("../evil",)),
                     (pp.venue_official_dirs, ("../evil",))):
        try:
            fn(*args, root=root)
            err = ""
        except pp.VenueProfileError as exc:
            err = str(exc)
        check(f"F78 {fn.__name__} refuses '../evil'", "invalid venue id" in err, err[:200])

    res, exc, err = quiet(pp.build_venue_templates, "../evil", root=root)
    check("F78 build-venue-templates refuses '../evil'", exc is not None, f"res={res!r}")
    check("F78 the refusal names the invalid id", "invalid venue id" in err, err[:300])
    check("F78 nothing was written outside the profile store",
          not (root.parent / "evil.templates").exists()
          and not (root / "venue_profiles" / ".." / ".." / "evil.templates").exists())

    ok = pp.build_venue_templates("v", root=root)
    check("F78 a valid id still builds inside the profile store",
          Path(ok["pack"]).resolve().is_relative_to(pdir.resolve()), ok.get("pack"))


def main() -> int:
    for fn in (test_f66, test_f67, test_f68, test_f69, test_f70, test_f71,
               test_f72, test_f73, test_f74, test_f75, test_f76, test_f78):
        try:
            fn()
        except Exception as exc:                                     # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append(f"{fn.__name__} raised {type(exc).__name__}")
        finally:
            cleanup()
    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): {', '.join(FAILS)}")
        return 1
    print("ALL WAVE-2 VENUE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

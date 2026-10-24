#!/usr/bin/env python3
"""The venue's MAIN-TEXT COUNTING CONVENTION (M19; audit finding C27).

The counter used to hard-code one convention -- the Nature Biotechnology
Article rule, which stops the main text at Methods and subtracts figure
legends. The venue profiles say otherwise for some venue/type pairs: Frontiers
counts the main body WITH Methods and in-text citations, and NBT's Brief
Communication counts 1,000-1,500 words INCLUDING abstract, references and figure
legends. `counting.main_text.excludes` now carries that rule per venue (and per
article type), and both counters read it.

Asserts:
  * the default (and the `generic` profile) keeps the NBT Article convention --
    abstract, Methods, references and figure legends excluded -- so a profile
    written before the field counts exactly as it always did;
  * the Frontiers profile counts Methods inside the main text, its figure
    captions still outside, and stops at References; every article type that
    does not state its own block inherits the venue-level one;
  * NBT's Brief Communication override counts the abstract, references and
    figure legends inside its main text;
  * `scripts/count_words.py` and the pipeline's code-side M19 scan return the
    SAME count for the same document and profile (script/pipeline parity);
  * the M19 prompt renderers name the profile's own span, and the default text
    still names the four excluded sections;
  * the schema is validated (unknown section kind, missing `excludes`, duplicate
    kind) and an explicit empty list means "nothing excluded";
  * a root snapshot recorded before the field existed inherits the shipped
    profile's convention, while a snapshot that carries its own block wins.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_counting", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_counting"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(path)
    return path


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def counter(manuscript: Path, *args: str):
    """(payload, stderr) from scripts/count_words.py --json, or (None, error)."""
    cmd = [sys.executable,
           str(WS / "paper-skills" / "paper-review" / "scripts" / "count_words.py"),
           str(manuscript), "--section", "main-text", "--json", *args]
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode != 0:
        return None, run.stderr.strip() or run.stdout.strip()
    return json.loads(run.stdout), ""


def main_row(payload):
    rows = [r for r in (payload or {}).get("rows") or [] if r["section"] == "main text"]
    return rows[0] if rows else None


# A manuscript shaped so every convention produces a different number:
#   abstract 3, introduction 4, Methods 6, caption 8, results 2, references 3.
MANUSCRIPT = """Abstract

one two three

Introduction

intro words here today

Methods

method words five six seven eight

Figure 1 | a caption of five words

Results

result words

References

ref one two

Acknowledgements

thanks
"""


def load(venue, **kwargs):
    return nb.load_venue_profile(venue, root=str(WS), **kwargs)


# =====================================================================
# CT1 - the default is the convention the counter always applied
# =====================================================================

def test_default():
    print()
    print("== CT1: no profile / generic profile keeps the NBT Article rule ==")
    default = nb.default_venue_profile()
    check("CT1 the default excludes the abstract, Methods, references and legends",
          {"abstract", "methods", "references", "figure-legends"}
          <= set(default.main_text_excludes()),
          str(default.main_text_excludes()))
    check("CT1 the default rule text names the four excluded sections",
          "the abstract, Methods, references and figure legends EXCLUDED"
          in nb.main_text_counting_text(default))
    check("CT1 the default review mandate names the four excluded sections",
          "Methods, references and figure legends EXCLUDED" in nb.m19_blocks()["review"])
    generic = load("generic")
    check("CT1 a profile that states no convention gets the default",
          set(generic.main_text_excludes()) == set(default.main_text_excludes()))

    tmp = scratch("c27_default_")
    ms = write(tmp / "ms.md", MANUSCRIPT)
    payload, err = counter(ms)
    row = main_row(payload)
    check("CT1 the counter (no profile) stops the main text at Methods",
          row is not None and row["words"] == 4, f"{row} {err}")
    check("CT1 the counter's JSON reports the convention it applied",
          (payload or {}).get("counting", {}).get("main_text", {}).get("excludes")
          == list(nb.DEFAULT_MAIN_TEXT_EXCLUDES), str((payload or {}).get("counting")))
    info = nb.scan_lengths_in_sources([(tmp, "", ())])
    scan = {(r["document"], r["section"]): r["words"] for r in info["rows"]}
    check("CT1 the code-side scan applies the same default (parity)",
          scan.get(("ms.md", "main text")) == 4, str(scan))


# =====================================================================
# CT2 - Frontiers counts Methods inside the main body
# =====================================================================

def test_frontiers():
    print()
    print("== CT2: Frontiers counts the main body WITH Methods ==")
    fr = load("frontiers-in-immunology")
    check("CT2 the Frontiers profile is loaded with its counting block",
          "methods" not in fr.main_text_excludes(),
          str(fr.main_text_excludes()))
    check("CT2 Frontiers still leaves the abstract, references and legends out",
          {"abstract", "references", "figure-legends"}
          <= set(fr.main_text_excludes()))
    check("CT2 a type that states no block inherits the venue convention",
          "methods" not in fr.with_article_type("review").main_text_excludes())
    rule = nb.main_text_counting_text(fr)
    check("CT2 the rendered rule says Methods is INSIDE the count",
          "Methods INSIDE the count" in rule, rule)
    check("CT2 the M19 review mandate carries the same clause",
          "Methods INSIDE the count" in nb.m19_blocks(fr)["review"])
    check("CT2 the default renderer is not silently replaced",
          "Methods INSIDE the count" not in nb.m19_blocks()["review"])

    tmp = scratch("c27_frontiers_")
    ms = write(tmp / "ms.md", MANUSCRIPT)
    payload, err = counter(
        ms, "--venue-profile", str(WS / "venue_profiles" / "frontiers-in-immunology.json"),
        "--article-type", "original-research")
    row = main_row(payload)
    # introduction 4 + Methods 6 + results 2, the 8-word legend subtracted
    check("CT2 the counter includes the Methods words and still drops the legend",
          row is not None and row["words"] == 12, f"{row} {err}")
    info = nb.scan_lengths_in_sources([(tmp, "", ())], profile=fr)
    scan = {(r["document"], r["section"]): r["words"] for r in info["rows"]}
    check("CT2 the code-side scan returns the same count (script/pipeline parity)",
          scan.get(("ms.md", "main text")) == row["words"] == 12, str(scan))
    check("CT2 the code-side scan carries the convention in its payload",
          "methods" not in (info.get("counting") or {}).get("main_text", {})
          .get("excludes", ["methods"]))


# =====================================================================
# CT3 - NBT's Brief Communication counts abstract/references/legends
# =====================================================================

def test_brief_communication():
    print()
    print("== CT3: Brief Communication counts the abstract, references and legends ==")
    brief = load("nature-biotechnology").with_article_type("brief-communication")
    check("CT3 the type's own block overrides the venue block",
          {"abstract", "references", "figure-legends"}
          .isdisjoint(brief.main_text_excludes())
          and "methods" not in brief.main_text_excludes(),
          str(brief.main_text_excludes()))
    check("CT3 the Article type still excludes Methods",
          "methods" in load("nature-biotechnology").main_text_excludes())
    check("CT3 the rendered rule says those sections are INSIDE the count",
          "abstract" in nb.main_text_counting_text(brief)
          and "INSIDE the count" in nb.main_text_counting_text(brief),
          nb.main_text_counting_text(brief))

    tmp = scratch("c27_brief_")
    ms = write(tmp / "ms.md", MANUSCRIPT)
    payload, err = counter(
        ms, "--venue-profile", str(WS / "venue_profiles" / "nature-biotechnology.json"),
        "--article-type", "brief-communication")
    row = main_row(payload)
    # abstract 3 + intro 4 + Methods 6 + legend 8 + results 2 + references 3 = 26
    check("CT3 the counter counts abstract/references/legends (26 words here)",
          row is not None and row["words"] == 26, f"{row} {err}")
    info = nb.scan_lengths_in_sources([(tmp, "", ())], profile=brief)
    scan = {(r["document"], r["section"]): r["words"] for r in info["rows"]}
    check("CT3 the code-side scan returns the same count (script/pipeline parity)",
          scan.get(("ms.md", "main text")) == row["words"] == 26, str(scan))


# =====================================================================
# CT4 - validation and the explicit empty list
# =====================================================================

def test_validation():
    print()
    print("== CT4: the counting block is validated at the profile boundary ==")

    def rejected(data):
        try:
            nb.VenueProfile(data)
        except nb.VenueProfileError:
            return True
        return False

    check("CT4 an unknown section kind is rejected",
          rejected({"id": "x", "counting": {"main_text": {"excludes": ["methodz"]}}}))
    check("CT4 a missing `excludes` list is rejected",
          rejected({"id": "x", "counting": {"main_text": {}}}))
    check("CT4 a duplicate kind is rejected",
          rejected({"id": "x", "counting": {"main_text":
                                            {"excludes": ["methods", "methods"]}}}))
    check("CT4 a non-object block is rejected",
          rejected({"id": "x", "counting": []}))
    empty = nb.VenueProfile({"id": "x", "counting": {"main_text": {"excludes": []}}})
    check("CT4 an explicit empty list means 'nothing excluded'",
          empty.main_text_excludes() == [])
    typed = nb.VenueProfile({"id": "x", "counting": {"main_text": {
        "excludes": ["Methods", "figure_legends"],
        "source": "s", "note": "n"}}})
    check("CT4 the profile carries the provenance and normalises the kinds",
          typed.main_text_excludes() == ["methods", "figure-legends"]
          and typed.counting["main_text"]["source"] == "s"
          and typed.counting["main_text"]["note"] == "n")


# =====================================================================
# CT5 - a pre-field snapshot inherits the shipped convention
# =====================================================================

def test_snapshot_inheritance():
    print()
    print("== CT5: a snapshot recorded before the field inherits the profile's block ==")
    shipped = WS / "venue_profiles" / "frontiers-in-immunology.json"
    data = json.loads(shipped.read_text(encoding="utf-8"))
    root = scratch("c27_snapshot_")
    (root / "venue_profiles").mkdir(parents=True)
    shutil.copy(shipped, root / "venue_profiles" / shipped.name)

    old = json.loads(json.dumps(data))
    old.pop("counting", None)
    prof = nb._snapshot_profile({"venue_profile": old}, "frontiers-in-immunology", root=root)
    check("CT5 a snapshot without the field inherits the shipped convention",
          prof is not None and "methods" not in prof.main_text_excludes(),
          str(prof.main_text_excludes() if prof else None))

    own = json.loads(json.dumps(data))
    own["counting"] = {"main_text": {"excludes": ["abstract", "methods"]}}
    prof2 = nb._snapshot_profile({"venue_profile": own}, "frontiers-in-immunology", root=root)
    check("CT5 a snapshot that carries its own block is authoritative",
          prof2 is not None and set(prof2.main_text_excludes()) == {"abstract", "methods"},
          str(prof2.main_text_excludes() if prof2 else None))

    # A pre-field snapshot of a venue whose TYPE counts differently must inherit
    # that type's block, not only the venue-level (default-type) one.
    nb_shipped = WS / "venue_profiles" / "nature-biotechnology.json"
    shutil.copy(nb_shipped, root / "venue_profiles" / nb_shipped.name)
    old_nb = json.loads(nb_shipped.read_text(encoding="utf-8"))
    old_nb.pop("counting", None)
    for entry in old_nb.get("article_types") or []:
        entry.pop("counting", None)
    prof3 = nb._snapshot_profile({"venue_profile": old_nb}, "nature-biotechnology", root=root)
    brief = (prof3.with_article_type("brief-communication")
             if prof3 is not None else None)
    check("CT5 a pre-field snapshot inherits a TYPE's own block (Brief Communication)",
          brief is not None
          and {"abstract", "references", "figure-legends"}
          .isdisjoint(brief.main_text_excludes()),
          str(brief.main_text_excludes() if brief else None))


def main() -> int:
    test_default()
    test_frontiers()
    test_brief_communication()
    test_validation()
    test_snapshot_inheritance()
    for path in TMPDIRS:
        shutil.rmtree(path, ignore_errors=True)
    print(f"\n{len(FAILS)} failed")
    for name in FAILS:
        print("  FAILED:", name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

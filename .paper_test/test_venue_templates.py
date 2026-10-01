#!/usr/bin/env python3
"""Venue exemplars -> a PINNED, structure-only advisory norm and templates.

A venue may ship `venue_profiles/<id>.manuscripts/` (recently published OA
articles of the venue). The pipeline reads them for their STRUCTURE ONLY and
derives `venue_profiles/<id>.templates/`:

  * `structure.json` + `venue_architecture.md` -- the modal section order,
    abstract presence and statement placement, with presence counts;
  * `word-template.md` + `latex-template.tex` -- the skeleton a producing
    session follows;
  * `MANIFEST.json` -- every input and output sha256-pinned (no timestamps), so
    two builds from the same exemplars are byte-identical.

The derived norm is ADVISORY: `review_prompt`/`rewrite_prompt` receive it only
when a pack exists, and the default prompts are unchanged without one.

Run:  python3 .paper_test/test_venue_templates.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("paperp_vt", WS / "paper_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["paperp_vt"] = np
spec.loader.exec_module(np)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


MD_A = """# Title A

## Abstract

text

## Introduction

text

## Results

text

## Discussion

text

## Methods

text

## Data availability

statement

## Funding

statement
"""

MD_B = """# Title B

## Abstract

text

## Introduction

text

## Results

text

## Methods

text

## Author contributions

statement
"""

TEX_C = r"""\documentclass{article}
\begin{document}
\begin{abstract}
text
\end{abstract}
\section{Introduction}
text
\subsection{Sub part}
text
\section{Results}
text
\section{Discussion}
text
\section{Methods}
text
\section*{Competing interests}
none
\end{document}
"""

OFFICIAL_TEX = r"""\documentclass{frontiersSCNS}
\begin{document}
\section{Introduction}
\section{Materials and Methods}
\section{Results}
\section{Discussion}
\section{Data Availability Statement}
\section{Author Contributions}
\section{Funding}
\section{Conflict of Interest}
\end{document}
"""

SUBMITTED_TEX = r"""\documentclass{article}
\begin{document}
\section{Introduction}
\section{Methods}
\section{Results}
\section{Discussion}
\end{document}
"""


def make_store(tmp: Path) -> Path:
    store = tmp / "venue_profiles"
    ex = store / "demo.manuscripts"
    ex.mkdir(parents=True)
    (ex / "a.md").write_text(MD_A, encoding="utf-8")
    (ex / "b.md").write_text(MD_B, encoding="utf-8")
    (ex / "c.tex").write_text(TEX_C, encoding="utf-8")
    (ex / "manifest.json").write_text(json.dumps([
        {"article": "a.md", "source_url": "https://example.org/a", "doi": "10.1/a",
         "license": "CC-BY", "retrieved": "2026-10-01"}]), encoding="utf-8")
    return store


def test_extraction_and_norm(tmp: Path):
    print("== structure extraction and the modal norm ==")
    md = np.extract_manuscript_structure(tmp / "venue_profiles" / "demo.manuscripts" / "a.md")
    check("a Markdown manuscript drops its title and keeps the section order",
          [s["title"] for s in md["sections"]] == ["Abstract", "Introduction", "Results",
                                                   "Discussion", "Methods", "Data availability",
                                                   "Funding"],
          str(md["sections"]))
    check("statement sections are detected by name",
          md["statements"] == ["Data availability", "Funding"], str(md["statements"]))
    tex = np.extract_manuscript_structure(tmp / "venue_profiles" / "demo.manuscripts" / "c.tex")
    check("a LaTeX manuscript carries its section levels (subsection = 2) and abstract",
          [(s["level"], s["title"]) for s in tex["sections"]][:3] ==
          [(1, "Introduction"), (2, "Sub part"), (1, "Results")]
          and tex["abstract"] is True, str(tex["sections"][:3]))
    recs = [np.extract_manuscript_structure(
        tmp / "venue_profiles" / "demo.manuscripts" / n) for n in ("a.md", "b.md", "c.tex")]
    norm = np.structure_norm(recs)
    check("the norm's body order is modal and excludes statement sections",
          [s["title"] for s in norm["sections"]] == ["Abstract", "Introduction", "Results",
                                                     "Discussion", "Methods"],
          str([s["title"] for s in norm["sections"]]))
    check("presence counts and the abstract count are reported",
          norm["n_exemplars"] == 3
          and next(s for s in norm["sections"] if s["title"] == "Introduction")["present"] == 3
          and norm["abstract_present"] == 3,
          str(norm["sections"]))
    check("statement placement counts are reported",
          {s["label"]: s["present"] for s in norm["statements"]} ==
          {"Data availability": 1, "Funding": 1, "Author contributions": 1,
           "Competing interests": 1},
          str(norm["statements"]))


def test_pack_and_templates(tmp: Path):
    print()
    print("== the pinned pack: summary, word/latex templates, manifest, determinism ==")
    store = tmp / "venue_profiles"
    first = np.build_venue_templates("demo", profiles_dir=store)
    pack = store / "demo.templates"
    check("the pack is written where the exemplars live",
          first.get("pack") == str(pack) and pack.is_dir(), str(first))
    for name in (np.VENUE_STRUCTURE_FILE, np.VENUE_NORM_FILE, np.VENUE_WORD_TEMPLATE,
                 np.VENUE_LATEX_TEMPLATE, np.VENUE_PACK_MANIFEST):
        check(f"the pack carries {name}", (pack / name).is_file())
    arch = (pack / np.VENUE_NORM_FILE).read_text(encoding="utf-8")
    check("the summary states the modal order with presence counts",
          "| 1 | Abstract | 2/3 |" in arch and "Introduction" in arch
          and "Statement placement" in arch and "ADVISORY" in arch, arch[:200])
    word = (pack / np.VENUE_WORD_TEMPLATE).read_text(encoding="utf-8")
    check("the Word skeleton is a Heading-styled section skeleton",
          "Word styles" in word and "# <Manuscript title>" in word
          and "## Abstract" in word and "## Introduction" in word
          and word.index("## Introduction") < word.index("## Methods"), word[:200])
    latex = (pack / np.VENUE_LATEX_TEMPLATE).read_text(encoding="utf-8")
    check("the LaTeX skeleton carries the same order and an abstract environment",
          "\\begin{abstract}" in latex and "\\section{Introduction}" in latex
          and latex.index("\\section{Introduction}") < latex.index("\\section{Methods}")
          and "\\section*{Data availability}" in latex, latex[:200])
    manifest = json.loads((pack / np.VENUE_PACK_MANIFEST).read_text(encoding="utf-8"))
    check("the manifest pins every output by sha256",
          set(manifest["files"]) == {np.VENUE_STRUCTURE_FILE, np.VENUE_NORM_FILE,
                                     np.VENUE_WORD_TEMPLATE, np.VENUE_LATEX_TEMPLATE}
          and all(np.sha256_file(pack / n) == h for n, h in manifest["files"].items()),
          str(manifest["files"]))
    check("the manifest pins every INPUT exemplar it was derived from",
          {e["file"] for e in manifest["generated_from"]} == {"a.md", "b.md", "c.tex"}
          and all(e["sha256"] for e in manifest["generated_from"]), str(manifest["generated_from"]))
    check("the downloader's provenance (source URL/doi/license) rides in the manifest",
          isinstance(manifest.get("sources"), list) and manifest["sources"]
          and manifest["sources"][0].get("source_url"), str(manifest.get("sources"))[:200])
    before = {p.name: np.sha256_file(p) for p in sorted(pack.rglob("*")) if p.is_file()}
    np.build_venue_templates("demo", profiles_dir=store)
    after = {p.name: np.sha256_file(p) for p in sorted(pack.rglob("*")) if p.is_file()}
    check("two builds from the same exemplars are byte-identical (pinned, no timestamps)",
          before == after, f"{sorted(before)}")


def test_prompt_norm(tmp: Path):
    print()
    print("== the norm reaches review/rewrite as an ADVISORY block ==")
    block = np.venue_norm_block("demo", root=tmp)
    check("venue_norm_block finds the pack through the root's venue_profiles/",
          "VENUE TEMPLATE / STRUCTURE" in block and "| 1 | Abstract | 2/3 |" in block
          and "sha256" in block, block[:200])
    check("the block forbids copying prose and says it is not a gate",
          "NEVER copy sentences" in block and "Neither tier is a gate" in block)
    check("a venue without a pack contributes no block",
          np.venue_norm_block("nosuchvenue", root=tmp) == "")
    nd = np.add_venue_prompt("demo", tmp / "store", want_download=False)
    check("--no-download turns the download section into an explicit skip",
          "SKIPPED: `--no-download`" in nd and "aim for 8-15" not in nd
          and "profile and the README row ONLY" in nd, nd[-200:])
    with_dl = np.add_venue_prompt("demo", tmp / "store")
    flat_dl = " ".join(with_dl.split())
    check("the default add-venue prompt asks for the OA downloads",
          "aim for 8-15" in flat_dl and "obey robots.txt" in flat_dl
          and "never bypass a login" in flat_dl)
    base_review = np.review_prompt(Path("/tmp/x"), "r1_review", 1)
    with_norm = np.review_prompt(Path("/tmp/x"), "r1_review", 1, venue_norm=block)
    check("the review prompt gains the block only when it is passed",
          "VENUE TEMPLATE / STRUCTURE" not in base_review
          and "VENUE TEMPLATE / STRUCTURE" in with_norm
          and with_norm.endswith(block))
    base_rw = np.rewrite_prompt(Path("/tmp/x"), "r1_w1", 1)
    with_rw = np.rewrite_prompt(Path("/tmp/x"), "r1_w1", 1, venue_norm=block)
    check("the rewrite prompt gains the block only when it is passed",
          "VENUE TEMPLATE / STRUCTURE" not in base_rw
          and "VENUE TEMPLATE / STRUCTURE" in with_rw)
    transfer_block = np.venue_norm_block("demo", root=tmp, transfer=True)
    check("the transfer clause names the target template as the replacement",
          "TRANSFER MODE" in transfer_block
          and "REPLACES the previous venue" in transfer_block
          and "TRANSFER MODE" not in block)


ADD_VENUE_STUB = '''#!/usr/bin/env python3
"""Test stub for `add-venue`: writes a valid profile, a README row, exemplars."""
import json, sys
from pathlib import Path
dest, vid = Path(sys.argv[1]), sys.argv[2]
profile = {
    "id": vid, "label": "Demo Venue", "short": "Demo",
    "journals": ["Demo Journal"], "accepts_any_journal": False,
    "default_article_type": "article",
    "article_types": [{"id": "article", "label": "Article",
                       "length_limits": {"abstract": {"base": 150, "relaxation": 15,
                                                      "note": "https://example.org/guide"},
                                         "main_text": {"base": 3000, "relaxation": 750,
                                                       "note": "https://example.org/guide"}},
                       "captions": {"default_limit": 0}}],
    "captions": {"default_limit": 0},
    "submission": {"cover_letter": "optional"},
    "prompt": {"venue_phrase": "a Demo Venue manuscript"},
    "description": "written by the test stub",
}
(dest / f"{vid}.json").write_text(json.dumps(profile, indent=1), encoding="utf-8")
readme = dest / "README.md"
readme.write_text((readme.read_text(encoding="utf-8") if readme.is_file() else "# Venue profiles\\n\\n")
                  + f"| `{vid}` | written by the test stub |\\n", encoding="utf-8")
ex = dest / f"{vid}.manuscripts"
ex.mkdir(parents=True, exist_ok=True)
(ex / "one.md").write_text("# T\\n\\n## Abstract\\n\\nx\\n\\n## Introduction\\n\\nx\\n"
                           "\\n## Results\\n\\nx\\n\\n## Methods\\n\\nx\\n", encoding="utf-8")
(ex / "two.tex").write_text("\\\\begin{document}\\n\\\\section{Introduction}\\nx\\n"
                            "\\\\section{Results}\\nx\\n\\\\section{Methods}\\nx\\n"
                            "\\\\end{document}\\n", encoding="utf-8")
Path("_pipeline_done.json").write_text(json.dumps(
    {"stage": "add-venue", "status": "complete", "error": None}), encoding="utf-8")
'''


def test_official_template(tmp: Path):
    print()
    print("== the OFFICIAL journal template: authoritative skeleton + conformance scan ==")
    store = tmp / "official_store"
    off = store / "official-venue.official"
    off.mkdir(parents=True)
    (off / "sample.tex").write_text(OFFICIAL_TEX, encoding="utf-8")
    (off / "requirements.json").write_text(json.dumps(
        {"mandatory_sections": ["Introduction", "Materials and Methods", "Results",
                                "Discussion"]}), encoding="utf-8")
    (off / "manifest.json").write_text(json.dumps([
        {"source_url": "https://example.org/Frontiers_LaTeX_Templates.zip",
         "archive": "Frontiers_LaTeX_Templates.zip", "files": ["sample.tex"],
         "retrieved": "2026-10-01", "license_note": "venue template, author reuse"}],
        indent=1), encoding="utf-8")
    (store / "official-venue.manuscripts").mkdir()
    (store / "official-venue.manuscripts" / "one.md").write_text(MD_A, encoding="utf-8")
    report = np.build_venue_templates("official-venue", profiles_dir=store)
    pack = store / "official-venue.templates"
    check("a pack is built from the official template + exemplars",
          report["official"] == 1 and report["exemplars"] == 1 and pack.is_dir(), str(report))
    check("the mandatory sections and the official class are reported",
          report["mandatory_sections"] == ["Introduction", "Materials and Methods", "Results",
                                           "Discussion"]
          and report["documentclass"] == "frontiersSCNS", str(report))
    structure = json.loads((pack / np.VENUE_STRUCTURE_FILE).read_text(encoding="utf-8"))
    check("structure.json carries the official block next to the norm",
          structure["official"]["documentclass"] == "frontiersSCNS"
          and structure["official"]["mandatory_sections"]
          and structure["norm"]["n_exemplars"] == 1, str(structure)[:200])
    arch = (pack / np.VENUE_NORM_FILE).read_text(encoding="utf-8")
    check("the summary puts the OFFICIAL tier above the advisory tier",
          arch.index("OFFICIAL journal template (AUTHORITATIVE)")
          < arch.index("Recent-practice structure (ADVISORY")
          and "Mandatory sections (must exist)" in arch, arch[:200])
    word = (pack / np.VENUE_WORD_TEMPLATE).read_text(encoding="utf-8")
    check("the Word skeleton marks the mandatory sections",
          "## Introduction [MANDATORY]" in word and "## Materials and Methods [MANDATORY]" in word
          and "## Data Availability Statement" in word, word[:300])
    latex = (pack / np.VENUE_LATEX_TEMPLATE).read_text(encoding="utf-8")
    check("the LaTeX skeleton uses the journal's own documentclass and order",
          "\\documentclass{frontiersSCNS}" in latex
          and "\\section{Materials and Methods}" in latex
          and latex.index("\\section{Introduction}") < latex.index("\\section{Discussion}"),
          latex[:200])
    manifest = json.loads((pack / np.VENUE_PACK_MANIFEST).read_text(encoding="utf-8"))
    check("the manifest pins the official files and their download provenance",
          any(f["file"] == "sample.tex" for f in manifest["official_files"])
          and manifest["official_sources"][0]["source_url"].endswith(".zip"), str(manifest)[:200])
    # The conformance scan: a corpus with the wrong class and a missing statement.
    reqs = np.official_template_requirements("official-venue", root=tmp.parent)
    reqs = json.loads((pack / np.VENUE_STRUCTURE_FILE).read_text(encoding="utf-8"))["official"]
    sub = tmp / "submission"
    sub.mkdir()
    (sub / "manuscript.tex").write_text(SUBMITTED_TEX, encoding="utf-8")
    conf = np.scan_template_conformance([(sub, "", ())], reqs)
    flat = " ".join(conf["missing_sections"] + conf["missing_statements"]).lower()
    check("the scan reports the missing mandatory sections and statements",
          "data availability" in flat and "author contributions" in flat
          and "funding" in flat and conf["class_ok"] is False
          and conf["conforms"] is False, str(conf)[:300])
    (sub / "manuscript.tex").write_text(
        OFFICIAL_TEX.replace("frontiersSCNS", "frontiersSCNS"), encoding="utf-8")
    conf_ok = np.scan_template_conformance([(sub, "", ())], reqs)
    check("a conforming corpus passes the code-side scan",
          conf_ok["conforms"] is True and conf_ok["missing_sections"] == []
          and conf_ok["missing_statements"] == [], str(conf_ok)[:200])
    # Official-only venues (no exemplars) still get a pack.
    off_only = store / "only-official.official"
    off_only.mkdir()
    (off_only / "sample.tex").write_text(OFFICIAL_TEX, encoding="utf-8")
    rep2 = np.build_venue_templates("only-official", profiles_dir=store)
    check("an official-only venue still gets a pack (no exemplars required)",
          rep2["official"] == 1 and rep2["exemplars"] == 0
          and (store / "only-official.templates" / np.VENUE_NORM_FILE).is_file(), str(rep2))
    check("the session sandbox declares the conformance evidence it seeds",
          any(str(p).endswith("work/OFFICIAL_TEMPLATE.json")
              for p in np.seeded_evidence_paths(tmp / "sb"))
          and any(str(p).endswith("review/work/OFFICIAL_TEMPLATE.md")
                  for p in np.seeded_evidence_paths(tmp / "sb")))


def test_add_venue_cli(tmp: Path):
    print()
    print("== add-venue: an agent writes the profile + downloads, the CODE derives the pack ==")
    store = tmp / "store"
    store.mkdir(parents=True, exist_ok=True)
    stub = tmp / "stub_add_venue.py"
    stub.write_text(ADD_VENUE_STUB, encoding="utf-8")
    cli = [sys.executable, str(WS / "paper_pipeline.py")]
    cmd = json.dumps([sys.executable, str(stub), str(store), "demo-venue"])
    r = subprocess.run(cli + ["add-venue", "demo-venue", "--profiles-dir", str(store),
                              "--agent-cmd", cmd, "--timeout", "120"],
                       capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    check("add-venue exits 0 with a valid profile and downloaded exemplars",
          r.returncode == 0, out[-400:])
    check("the profile JSON was written and validates",
          (store / "demo-venue.json").is_file()
          and np.VenueProfile(json.loads((store / "demo-venue.json").read_text(encoding="utf-8")))
          .id == "demo-venue", out[-200:])
    check("venue_profiles/README.md gained a row",
          "demo-venue" in (store / "README.md").read_text(encoding="utf-8"))
    check("the derived pack exists and names the modal sections",
          (store / "demo-venue.templates" / np.VENUE_NORM_FILE).is_file()
          and "Introduction" in
          (store / "demo-venue.templates" / np.VENUE_NORM_FILE).read_text(encoding="utf-8"),
          out[-300:])
    # An agent that writes a broken profile is reported, and the exit is non-zero.
    broken = tmp / "stub_broken.py"
    broken.write_text("#!/usr/bin/env python3\nprint('did nothing')\n", encoding="utf-8")
    r2 = subprocess.run(cli + ["add-venue", "broken-venue", "--profiles-dir", str(store),
                               "--agent-cmd", json.dumps([sys.executable, str(broken)]),
                               "--timeout", "120"],
                        capture_output=True, text=True, timeout=600)
    out2 = r2.stdout + r2.stderr
    check("a session that writes no profile is reported as a PROBLEM with exit 1",
          r2.returncode == 1 and "broken-venue.json was not written" in out2, out2[-300:])
    # No exemplars at all: the deterministic command reports it and writes nothing.
    r3 = subprocess.run(cli + ["build-venue-templates", "--venue", "empty-venue",
                               "--profiles-dir", str(store)],
                        capture_output=True, text=True, timeout=300)
    check("build-venue-templates with no exemplars exits 2 and names the store",
          r3.returncode == 2 and "no readable exemplars" in (r3.stdout + r3.stderr)
          and not (store / "empty-venue.templates").exists(), (r3.stdout + r3.stderr)[-200:])


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="paper_vt_"))
    make_store(tmp)
    test_extraction_and_norm(tmp)
    test_pack_and_templates(tmp)
    test_prompt_norm(tmp)
    test_official_template(tmp)
    test_add_venue_cli(tmp)
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL VENUE-TEMPLATE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

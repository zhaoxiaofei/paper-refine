#!/usr/bin/env python3
"""`raw_data/` is the EVIDENCE area -- never submission content and never prose.

Run:  python3 .paper_test/test_raw_data_evidence_area.py

The operator's corpus carries `raw_data/` next to the submitted documents (main
text, cover letter, supplementary information) with data tables, figure sources,
the analysis snapshot -- and often the editors'/reviewers' feedback the authors
received (the motivating file:
`raw_data/iScience_feedback_from_reviewers_and_editors.txt`). The area is
byte-immutable (see test_raw_data_readonly.py) AND it is not a submission
document, so its text must never be:

  * role-classified as main text / cover letter / supplementary (a file named
    `raw_data/cover_letter.csv` is a data file, not a letter);
  * converted into the sweep corpus (`WORK/corpus/`) -- it goes to
    `WORK/evidence/` instead, and extract_acronyms.py skips it defensively;
  * counted (M18 caption lengths, M19 word limits, count_words.py);
  * scanned by the code-side caption / length / formatting / placeholder /
    number-provenance / document-set checks;
  * quoted as the authors' words: editors'/reviewers' feedback is external prose.

It stays available as EVIDENCE: the M30 producer tier and the fact-checking
reference (the pipeline prompt and the shared block say so in so many words).
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
SCRIPTS = WS / "paper-skills" / "paper-review" / "scripts"
spec = importlib.util.spec_from_file_location("paper_ev", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_ev"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def build_corpus(root: Path) -> Path:
    """A submission with a raw_data/ evidence area (data + feedback)."""
    sub = root / "sub"
    (sub / "raw_data").mkdir(parents=True)
    (sub / "manuscript_main_text.txt").write_text(
        "Abstract\nWe used scRNA-seq to profile the samples.\n\n"
        "Introduction\nscRNA-seq was performed once (scRNA-seq).\n\n"
        "Methods\nThe pipeline ran at 4 degrees C.\n", encoding="utf-8")
    (sub / "cover_letter_manuscript.txt").write_text(
        "Dear Editor,\nWe submit our manuscript using scRNA-seq.\nSincerely,\nThe Authors\n",
        encoding="utf-8")
    (sub / "supp_info.txt").write_text(
        "Supplementary Information\nSupplementary Figure 1 | A legend.\n", encoding="utf-8")
    (sub / "raw_data" / "dataset_summary-4f3a9c1.tsv").write_text(
        "gene\tMALBAC\tGRCh38\nA\t1\t2\n", encoding="utf-8")
    (sub / "raw_data" / "cover_letter.csv").write_text(
        "draft notes for the letter\n", encoding="utf-8")
    (sub / "raw_data" / "main_text_notes.txt").write_text(
        "Abstract\nThese are the reviewer's own notes about the abstract.\n\n"
        "Figure 1 | A caption-shaped line in the evidence area.\n"
        "Please [AUTHOR TO COMPLETE: address reviewer point 3].\n", encoding="utf-8")
    (sub / "raw_data" / "iScience_feedback_from_reviewers_and_editors.txt").write_text(
        "Dear Dr. Xie,\nThe reviewers raised several critical issues. MALBAC is mentioned.\n",
        encoding="utf-8")
    return sub


def main() -> int:
    tmp = scratch("paper_ev_")
    sub = build_corpus(tmp)
    work = tmp / "review" / "work"
    out = tmp / "review"

    print("== E1: convert_corpus.py -- the evidence area is not submission content ==")
    r = subprocess.run([sys.executable, str(SCRIPTS / "convert_corpus.py"),
                        "--submission", str(sub), "--work", str(work)],
                       capture_output=True, text=True)
    check("E1 convert_corpus runs", r.returncode == 0, r.stderr[-300:])
    inv = json.loads((work / "inventory.json").read_text(encoding="utf-8"))
    by_path = {e["path"]: e for e in inv}
    ev = [e for e in inv if e["path"].startswith("raw_data/")]
    check("E1 every raw_data file is inventoried", len(ev) == 4, str(sorted(by_path)))
    check("E1 every raw_data file has area=raw_data and editable=false",
          all(e["area"] == "raw_data" and e["editable"] is False for e in ev))
    check("E1 no raw_data file gets a submission document role",
          all(e["role"] in ("raw data (evidence)",
                            "reviewer/editor feedback (raw-data evidence)")
              for e in ev),
          str([(e["path"], e["role"]) for e in ev]))
    check("E1 the feedback file is labelled external feedback",
          by_path["raw_data/iScience_feedback_from_reviewers_and_editors.txt"]["role"]
          == "reviewer/editor feedback (raw-data evidence)")
    check("E1 'raw_data/cover_letter.csv' is NOT a cover letter",
          by_path["raw_data/cover_letter.csv"]["role"] == "raw data (evidence)")
    check("E1 the submission files keep their normal roles/areas",
          by_path["cover_letter_manuscript.txt"]["area"] == "submission"
          and by_path["cover_letter_manuscript.txt"]["role"] == "cover letter"
          and by_path["supp_info.txt"]["role"] == "supplementary")

    corpus_files = sorted(p.name for p in (work / "corpus").iterdir())
    evidence_files = sorted(p.name for p in (work / "evidence").iterdir())
    check("E1 no raw_data text is written into WORK/corpus",
          not any(n.startswith(("raw_data__", "raw_figs__")) for n in corpus_files),
          str(corpus_files))
    check("E1 raw_data text goes to WORK/evidence",
          any("iScience_feedback" in n for n in evidence_files)
          and any("dataset_summary" in n for n in evidence_files),
          str(evidence_files))
    check("E1 the converter says so on stdout",
          "evidence-area" in r.stdout and "Evidence text" in r.stdout)

    print("== E2: extract_acronyms.py -- no M1/M1b row from evidence prose ==")
    r = subprocess.run([sys.executable, str(SCRIPTS / "extract_acronyms.py"),
                        "--work", str(work), "--out", str(out)],
                       capture_output=True, text=True)
    check("E2 extract_acronyms runs", r.returncode == 0, r.stderr[-300:])
    md = (out / "artifacts" / "M1_acronyms.md").read_text(encoding="utf-8")
    check("E2 the submission token IS inventoried", "scRNA-seq" in md)
    check("E2 no token from a data table", "MALBAC" not in md and "GRCh38" not in md)
    check("E2 the artifact header carries the evidence-exclusion section",
          "Raw-data evidence / external feedback excluded" in md)
    check("E2 no M1 row cites a raw_data file",
          "raw_data__" not in md and "raw_figs__" not in md)
    # Defense in depth for a WORK/corpus/ produced by an older converter or an
    # adapted workflow: a stray evidence file must be skipped AND named.
    (work / "corpus" / "raw_data__legacy_feedback.txt.txt").write_text(
        "MALBAC legacy residue\n", encoding="utf-8")
    out2 = tmp / "review2"
    r = subprocess.run([sys.executable, str(SCRIPTS / "extract_acronyms.py"),
                        "--work", str(work), "--out", str(out2)],
                       capture_output=True, text=True)
    md2 = (out2 / "artifacts" / "M1_acronyms.md").read_text(encoding="utf-8")
    check("E2 a stray evidence file in WORK/corpus is skipped and named",
          r.returncode == 0 and "MALBAC" not in md2
          and "raw_data__legacy_feedback.txt.txt" in md2, r.stderr[-200:])

    print("== E3: count_words.py refuses an evidence path ==")
    r = subprocess.run([sys.executable, str(SCRIPTS / "count_words.py"),
                        str(sub / "raw_data" / "iScience_feedback_from_reviewers_and_editors.txt"),
                        "--section", "cover-letter"],
                       capture_output=True, text=True)
    check("E3 a feedback file is not counted", r.returncode != 0 and "EVIDENCE" in r.stderr,
          r.stdout + r.stderr)
    r = subprocess.run([sys.executable, str(SCRIPTS / "count_words.py"),
                        str(sub / "manuscript_main_text.txt"), "--json"],
                       capture_output=True, text=True)
    check("E3 a submission file is still counted", r.returncode == 0, r.stderr[-200:])

    print("== E4: the pipeline's code-side scans skip the evidence area ==")
    sources = [(sub, "", ())]
    lens = nb.scan_lengths_in_sources(sources)
    check("E4 M19 length scan counts the manuscript",
          any("manuscript" in d for d in lens["documents"]), str(lens["documents"]))
    check("E4 M19 never counts an evidence file",
          not any("raw_data" in d for d in lens["documents"])
          and not any("raw_data" in r["document"] for r in lens["rows"]))
    caps = nb.scan_captions_in_sources(sources, limit=0)
    check("E4 M18 never enumerates an evidence 'caption'",
          not any("raw_data" in c["document"] for c in caps["captions"]),
          str(caps["captions"])[:200])
    ph = nb.scan_placeholders_in_sources(sources)
    check("E4 the placeholder scan ignores evidence markers",
          not any("raw_data" in d for d in ph["files"]), str(ph["files"]))
    names = [n for n, _rows in nb.corpus_text_documents(sources)]
    check("E4 corpus_text_documents excludes the evidence area",
          not any(n.startswith("raw_data/") for n in names), str(names))

    base, cand = tmp / "base", tmp / "cand"
    for d in (base, cand):
        (d / "raw_data").mkdir(parents=True)
        (d / "raw_data" / "x.csv").write_text("a\n", encoding="utf-8")
    (cand / "raw_data" / "added-by-an-agent.csv").write_text("b\n", encoding="utf-8")
    dset = nb.document_set_check([(base, "", ())], [(cand, "", ())])
    check("E4 the document-set check has no evidence rows",
          not dset["added"] and not dset["missing"] and not dset["duplicates"],
          json.dumps(dset)[:300])
    docs = nb.collect_documents([(cand, "", ())])
    check("E4 collect_documents excludes the evidence area",
          all("raw-data" not in k for k in docs), str(list(docs)))

    print("== E5: the prompts carry the rule ==")
    shared = nb.shared_blocks()
    check("E5 the shared block names the evidence area",
          "THE EVIDENCE AREAS ARE READ-ONLY" in shared
          and "NEVER SUBMISSION CONTENT" in shared
          and "human_review_feedback" in shared
          and "never quote it as something \"the submission says\"" in shared)
    check("E5 the review directives name the evidence area",
          all(s in " ".join(nb.REVIEW_DIRECTIVES.split())
              for s in ("EVIDENCE areas", "human_review_feedback/", "llm_review_feedback/",
                        "a submission document", "None is part of the submission")))

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print("  -", f)
        return 1
    print("ALL raw_data EVIDENCE-AREA CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        cleanup()

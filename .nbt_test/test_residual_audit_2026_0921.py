#!/usr/bin/env python3
"""Residual-issue audit (2026-09-21/22): the decision layer, the auditor stage and
the provenance pack.

Run:  python3 .nbt_test/test_residual_audit_2026_0921.py

The operator's report against `r1_a2_revise/revised/` was, in one line: the code
had already ENUMERATED the problems and the pipeline threw them away. This suite
pins the countermeasures, each one a class rather than an instance:

  * the tiered sentence-length bar (an abstract sentence of exactly 45 words is a
    finding; a 50-word Methods sentence is not; a 61-word one is advisory),
  * `FMT-T8c` promoted from "report only" to a finding-tier redundancy rule,
  * `FMT-T9f` (a term the manuscript has to gloss), `FMT-T9i` (mega-paragraph)
    and `FMT-T9j` (two term families competing for one concept: CN vs CNV),
  * `FMT-T9g` (siunitx) with its exemption list, wired into the LaTeX sources,
  * the placeholder/identifier LOOKUP engine (kinds, plans, verdicts, the
    `skipped` mode) and the number reconciliation that PROVES a value from a
    shipped data table,
  * the disposition detectors (boilerplate closures, echoed OUTLINE summaries),
  * the AUDITOR stage: its artifact contract, the drop/add split, and the plan
    wiring (`review -> audit -> revise`, `--only audit`),
  * `collect_residuals` -> `decide --residual-gate`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nb = _load("nbt_residual", WS / "nbt_pipeline.py")
fmt = _load("nbt_fmt_residual", WS / "nbt_docx_format.py")

STUB = WS / ".nbt_test" / "stub_agent.py"
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


def cli(*argv, timeout=900):
    return subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


def make_text_corpus(dirp: Path) -> None:
    """Word-free corpus: the stub does not render pages, so a DOCX would trip the
    (correct) visual-artifact gate."""
    dirp.mkdir(parents=True, exist_ok=True)
    (dirp / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 90).strip() + "\n\nIntroduction\n\n"
        + ("text " * 120).strip() + "\n\nFigure 1 | A legend here.\n\nMethods\n\nx\n",
        encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. the scanner: tiered bars and the new rule families
# ---------------------------------------------------------------------------

ABSTRACT_SENTENCE = (
    "Ginkgo gave the best overall balance across the six metrics — a qualitative ranking — "
    "among the eight competing callers, largely through more accurate ploidy estimation, "
    "corroborated by fluorescence-activated cell sorting (FACS) with "
    "4′,6-diamidino-2-phenylindole (DAPI) staining in breast cancers and by the "
    "karyotype-defined HG008 subpopulations.")


def test_sentence_bar_tiers():
    print()
    print("== the sentence bar is section-aware (the abstract sentence is inside it) ==")
    rows = fmt.long_text_rows([ABSTRACT_SENTENCE], [False], ["abstract"])
    hit = [r for r in rows if r["rule"] == "FMT-T9c" and "long sentence" in r["evidence"]]
    check("the abstract's 45-word sentence is a finding", bool(hit), str(rows)[:160])
    check("... and it is MEDIUM severity, finding tier",
          bool(hit) and hit[0]["severity"] == "medium" and hit[0]["tier"] == "finding",
          str(hit[:1]))
    body = fmt.long_text_rows([ABSTRACT_SENTENCE], [False], ["body"])
    check("the same sentence in the body is INSIDE the body bar (46, >=)",
          not [r for r in body if "long sentence" in r["evidence"]])
    body_long = " ".join(["word"] * 46) + "."
    check("a 46-word body sentence IS a row (the old >45 behaviour, kept)",
          any("long sentence" in r["evidence"]
              for r in fmt.long_text_rows([body_long], [False], ["body"])))
    short_methods = " ".join(["word"] * 50) + "."
    check("a 50-word Methods sentence is NOT a finding",
          not [r for r in fmt.long_text_rows([short_methods], [False], ["methods"])
               if "long sentence" in r["evidence"]])
    long_methods = " ".join(["word"] * 61) + "."
    mrows = [r for r in fmt.long_text_rows([long_methods], [False], ["methods"])
             if "long sentence" in r["evidence"]]
    check("a 61-word Methods sentence is recorded as ADVISORY",
          bool(mrows) and mrows[0]["tier"] == "advisory", str(mrows[:1])[:160])
    mega = fmt.long_text_rows(["word " * 260], [False], ["body"])
    check("a 260-word paragraph is a FMT-T9i structural row",
          any(r["rule"] == "FMT-T9i" and r["tier"] == "finding" for r in mega), str(mega)[:160])
    enum = fmt.long_text_rows(["(1) a. (2) b. (3) c. (4) d. " + "word " * 210], [False], ["body"])
    check("a 4-item enumeration inside one paragraph stays a finding-tier row",
          any("enumerated items" in r["evidence"] and r["tier"] == "finding" for r in enum))


def test_repetition_and_gloss_and_concepts():
    print()
    print("== redundancy, self-glossed terms and competing term families ==")
    letter = ("We submit to Nature Biotechnology. Nature Biotechnology publishes such work. "
              "Nature Biotechnology readers will care. This fits Nature Biotechnology.")
    rep = [r for r in fmt.term_repetition_rows([letter + " " + "padding " * 40], [False])
           if "nature biotechnology" in r["evidence"].lower()]
    check("a journal name repeated in one short passage is a finding-tier row",
          bool(rep) and rep[0]["severity"] == "medium" and fmt.tier_of("FMT-T8c") == "finding",
          str(rep[:1])[:160])
    gloss = [r for r in fmt.self_gloss_rows(
        ["We assessed performance as a function of donor, sample cell type, average spot length "
         "(sequencing read length, which is associated with single-cell sequencing technology)."],
        [False])]
    check("a term the manuscript has to gloss is FMT-T9f", bool(gloss)
          and gloss[0]["rule"] == "FMT-T9f", str(gloss[:1])[:160])
    acronym = [r for r in fmt.self_gloss_rows(
        ["We used MALBAC (multiple annealing and looping-based amplification cycles) data."],
        [False])]
    check("an acronym long form is NOT a self-gloss row", not acronym, str(acronym))
    mixed = ("Copy-number (CN) callers estimate the copy-number state, whereas CNV callers "
             "call copy-number variations; the CNV call is a gain/loss decision.")
    fam = fmt.concept_family_rows([mixed], [False])
    check("CN vs CNV is FMT-T9j", any(r["rule"] == "FMT-T9j" for r in fam), str(fam)[:160])
    seed = fmt.glossary_seed_rows([mixed], [False])
    check("the GLOSSARY scaffold carries the concept and its counts",
          bool(seed) and any("CN" in str(r.get("concept")) for r in seed), str(seed[:1])[:160])


def test_latex_siunitx_rule():
    print()
    print("== FMT-T9g: siunitx, with its exemptions ==")
    text = ("The region spans 200~kb and 4.8--9.5\\% of the genome; "
            "\\code{175 kb} and \\qty{10}{\\percent} are exempt, as is $50$ kb.")
    rows = fmt.latex_number_rows(text)
    check("a unit-bearing value outside siunitx is flagged", bool(rows), str(rows)[:120])
    check("\\qty{}{} / \\code{} / math are NOT flagged",
          "175" not in rows[0]["evidence"] and "50" not in rows[0]["evidence"],
          rows[0]["evidence"] if rows else "")
    check("the row is finding tier", bool(rows) and rows[0]["tier"] == "finding")
    tmp = scratch("nbt_residual_tex_")
    (tmp / "si.tex").write_text(text, encoding="utf-8")
    info = nb.scan_format_in_sources([(tmp, "", ())], policy={})
    tex_rows = [r for r in info["rows"] if r["rule"] == "FMT-T9g"]
    check("the LaTeX sources carry the siunitx rule with a tier",
          bool(tex_rows) and tex_rows[0].get("tier") == "finding", str(tex_rows[:1])[:160])


# ---------------------------------------------------------------------------
# 2. the lookup engine and the number reconciliation
# ---------------------------------------------------------------------------


def test_placeholder_kinds_and_plan():
    print()
    print("== searchable markers are classified and routed to a lookup ==")
    rows = fmt.placeholder_ledger([
        "Preprints: [AUTHOR TO COMPLETE: state whether this work has been posted to a preprint "
        "server; if it has, name the server and the DOI, otherwise write \"not posted\".]",
        "Data: [AUTHOR TO COMPLETE: add the persistent identifier (DOI) of the archived copy.]",
        "Funding: [AUTHOR TO COMPLETE: if X.G.Z. also secured funding, add the funder.]",
    ])
    kinds = {(r["payload"][:12], r["class"], r["kind"]) for r in rows}
    check("the preprint marker is searchable/preprint",
          any(c == "searchable" and k == "preprint" for _p, c, k in kinds), str(kinds))
    check("the archived-copy marker routes to the archive lookup",
          any(c == "searchable" and k == "archive" for _p, c, k in kinds), str(kinds))
    check("the funding marker stays author-only",
          any(c == "author-only" for _p, c, k in kinds), str(kinds))
    docs = [("coverLetter.docx", [
        ("Manuscript title: CopyNumBench: benchmarking copy-number inference from single-cell "
         "whole-genome sequencing data", False, False),
        ("The code is at https://github.com/zhaoxiaofei/copy-num-bench-scwgs and the data at "
         "https://doi.org/10.1038/nbt.4060 (SRP026609).", False, False)])]
    plan = fmt.placeholder_lookup_plan(rows, docs)
    queries = {}
    for p in plan:
        queries.setdefault(p["kind"], []).append(p["query"])
    check("the preprint query is the manuscript title",
          any("CopyNumBench" in q for q in queries.get("preprint") or []), str(queries))
    check("the archive query includes the repository URL",
          any("github.com" in q for q in queries.get("archive") or []), str(queries))
    bad = fmt.lookup_kind("nonsense-kind", "x")
    check("an unknown kind degrades to verdict=error (never raises)",
          bad["verdict"] == "error" and bool(bad["errors"]))


def test_lookup_batch_offline_and_numbers():
    print()
    print("== the lookup batch honours `--placeholder-lookup off`; numbers are proved ==")
    ctx = type("C", (), {"cfg": {"placeholder_lookup": "off"}})()
    rows = nb._lookup_batch(ctx, [{"kind": "preprint", "query": "CopyNumBench"}], "unit")
    check("lookup off -> verdict `skipped` (the pipeline says it did NOT check)",
          rows and rows[0]["verdict"] == "skipped", str(rows))
    tables = [("dataset_summary.tsv",
               "dataset\tn_cells_total\tsample_mean_ploidy\n"
               "A\t64\t1.773\nB\t2055\t2.2\nC\t1046\t3.823\nD\t42200\t2.0\n")]
    ledger = fmt.number_ledger(["The 41 datasets yielded 45,365 cells; the largest had 2,055 "
                                "cells and ploidies from 1.77 to 3.82."])
    res = fmt.reconcile_number_rows(ledger, tables)
    sources = {r["number"]: r.get("source") or "" for r in ledger}
    check("45,365 is PROVED as a column sum", "sum" in sources.get("45,365", ""),
          str(sources))
    check("2,055 is PROVED as a cell value", "value in column" in sources.get("2,055", ""),
          str(sources))
    check("1.77/3.82 are PROVED by rounding a cell", bool(sources.get("1.77"))
          and bool(sources.get("3.82")), str(sources))
    check("the reconciliation reports what it filled", res["filled"] >= 4, str(res))
    unproved = fmt.number_ledger(["We analysed 120 HG008 cells."])
    fmt.reconcile_number_rows(unproved, tables)
    check("a number no shipped table proves stays UNSOURCED (the session's job)",
          not (unproved[0].get("source") or ""), str(unproved))
    # The lookup budget is allocated per class, so a corpus full of DOIs cannot
    # starve the gene check (the first cut of this spent all eight on DOIs and
    # silently never asked HGNC anything).
    targets = ([{"source": "identifier", "kind": "doi", "query": f"10.1/{i}"}
                for i in range(10)]
               + [{"source": "gene", "kind": "gene", "query": f"G{i}"} for i in range(10)]
               + [{"source": "placeholder", "kind": "preprint", "query": "T"}])
    picked = nb._select_lookup_targets(targets, nb.LOOKUP_MAX_TARGETS)
    srcs = Counter(t["source"] for t in picked)
    check("the lookup budget reserves room for every class",
          srcs["gene"] >= 3 and srcs["identifier"] >= 3 and srcs["placeholder"] >= 1,
          str(dict(srcs)))


def test_gene_symbol_ledger():
    print()
    print("== gene symbols are verified against HGNC ==")
    rows = fmt.gene_symbol_rows([
        ("m.tex", "We observed 50-fold amplification of KRAS in the tumour; "
                  "the PTPRC (CD45) marker and 175 kb bins are unrelated; hg19, v2.4.1.")])
    syms = [r["symbol"] for r in rows]
    check("a gene in gene language is extracted", "KRAS" in syms, str(syms))
    check("units/versions/identifiers are not candidates",
          not any(s in syms for s in ("V2", "HG19", "KB")), str(syms))
    check("the ranking puts the letters-only gene-language symbol first",
          rows and rows[0]["symbol"] == "KRAS", str([(r["symbol"], r["score"]) for r in rows[:3]]))
    # ONE call per query, and each verdict judged on its own: the old check asked
    # three times and accepted `absent` only from the FIRST call (else `error` from
    # the second), so a flaky HGNC -- timeout, then a good answer -- read as a
    # failure even though both verdicts are documented outcomes. The live API is
    # allowed to be unreachable here (`error` is the offline verdict), but a real
    # symbol that DOES resolve must come back with its accession.
    nonsense = fmt.lookup_kind("gene", "NOPE9", timeout=10)
    real = fmt.lookup_kind("gene", "KRAS", timeout=10)
    check("the HGNC lookup classifies a nonsense symbol as absent (offline: error)",
          nonsense["verdict"] in ("absent", "error"), str(nonsense["verdict"]))
    check("the HGNC lookup resolves a real symbol when the API answers",
          real["verdict"] in ("found", "error")
          and (real["verdict"] != "found"
               or [h.get("hgnc_id") for h in real["hits"]] == ["HGNC:6407"]),
          f"{real['verdict']} {[h.get('hgnc_id') for h in real['hits']]}")


# ---------------------------------------------------------------------------
# 3. the decision layer: boilerplate dispositions, outline echoes, residuals
# ---------------------------------------------------------------------------


def test_disposition_detectors():
    print()
    print("== boilerplate closures and echoed OUTLINE summaries are detected ==")
    boiler = [{"rule": "FMT-T9c", "severity": "low",
               "disposition": "OK — editorial preference only, no journal rule"}
              for _ in range(30)]
    probs = nb.disposition_artifact_problems(boiler)
    check("30 identical 'no journal rule' closures are a boilerplate problem",
          any("SAME sentence" in p for p in probs), str(probs)[:200])
    specific = [{"rule": "FMT-T9c", "severity": "low",
                 "disposition": f"OK — FMT-T9c: Methods enumeration, bar 61 words, this row is 47"}
                for _ in range(30)]
    check("the same number of RULE-SPECIFIC dispositions is clean",
          not nb.disposition_artifact_problems(specific))
    empty = [{"rule": "FMT-T9c", "severity": "low", "disposition": ""} for _ in range(3)]
    check("empty disposition cells are a problem",
          any("EMPTY" in p for p in nb.disposition_artifact_problems(empty)))
    outline = [{"first sentence": "The main workflow consisted of four steps.",
                "summary": "The main workflow consisted", "disposition": "OK — one topic"}
               for _ in range(20)]
    oprobs = nb.outline_artifact_problems(outline)
    check("echoed summaries are detected", any("copies of the row's first" in p for p in oprobs),
          str(oprobs)[:200])
    check("one identical OUTLINE verdict on every row is detected",
          any("same verdict" in p for p in oprobs), str(oprobs)[:200])
    good = [{"first sentence": "The main workflow consisted of four steps.",
             "summary": "Four-step benchmark workflow: normalize, simulate, call, score",
             "disposition": f"OK — FMT-T9c: heading-scoped, row {i}"} for i in range(20)]
    check("generated summaries with per-row verdicts are clean",
          not nb.outline_artifact_problems(good), str(nb.outline_artifact_problems(good))[:160])


def test_markdown_table_roundtrip():
    print()
    print("== the detectors read the SEEDED tables, not a private format ==")
    tmp = scratch("nbt_residual_tbl_")
    p = tmp / "M20_formatting.md"
    p.write_text("# M20\n\n| # | rule | tier | disposition |\n|---|---|---|---|\n"
                 "| 1 | FMT-T9c | finding | OK — FMT-T9c: body bar 46, this row is 44 |\n"
                 "| 2 | FMT-T8c | finding |  |\n", encoding="utf-8")
    rows = nb.parse_markdown_table(p)
    check("the markdown table parser reads header -> cell", len(rows) == 2
          and rows[0]["rule"] == "FMT-T9c" and rows[1]["tier"] == "finding", str(rows))
    probs = nb.disposition_artifact_problems(rows)
    check("a rule-specific OK is accepted and the empty row is reported",
          len(probs) == 1 and "EMPTY" in probs[0], str(probs))


def test_delivered_table_shapes():
    """The table shapes real review sessions deliver (2026-09-22 real root).

    A complete 2-round review failed three 30-minute attempts in a row on
    "EMPTY disposition cell" messages that were the PARSER's fault: a session
    that appends its verdict after the seeded empty cell, a session that adds a
    second table (the M20 "classes the scan cannot see"), an escaped `\\|` inside
    a caption, and a stray leading empty cell each made the row wider than its
    header, and the positional zip() then read the disposition from the wrong
    column (or read the second table's rows against the first table's header).
    """
    print()
    print("== delivered table shapes: appended verdicts, added tables, escaped pipes ==")
    tmp = scratch("nbt_shapes_")
    art = tmp / "artifacts"
    art.mkdir()
    # (a) verdict APPENDED after the seeded empty disposition cell
    (art / "M20_formatting.md").write_text(
        "| # | rule | severity | disposition |\n|---|---|---|---|\n"
        "| 1 | FMT-T1 | medium |  | OK — FMT-T1: covered by finding F-001 |\n"
        "| 2 | FMT-T9c | low |  | unable — no rule recorded for this row |\n",
        encoding="utf-8")
    # (b) a SECOND table with its own columns (the added "classes the scan cannot see")
    (art / "M19_length.md").write_text(
        "| # | section | words | disposition |\n|---|---|---|---|\n"
        "| 1 | abstract | 150 | OK — inside the 172-word cap |\n\n"
        "## Rows added from the manual pass\n\n"
        "| # | check | disposition |\n|---|---|---|\n"
        "| A1 | cover letter | OK — 400 words, inside the 300-500 preference |\n",
        encoding="utf-8")
    # (c) an escaped pipe inside a caption cell + a stray leading empty cell
    (art / "M18_caption_words.md").write_text(
        "| # | document | caption | disposition |\n|---|---|---|---|\n"
        "| | 1 | main.docx | Fig. 1 \\| Benchmarking | OK — 134 words, recorded |\n",
        encoding="utf-8")
    rows = nb.parse_markdown_table(art / "M20_formatting.md")
    check("an appended verdict is read as the disposition (not dropped by zip)",
          [r.get("disposition") for r in rows]
          == ["OK — FMT-T1: covered by finding F-001",
              "unable — no rule recorded for this row"], str(rows))
    check("dispositioned appended rows are no longer an EMPTY problem",
          not nb.disposition_artifact_problems(rows))
    notes = nb.artifact_quality_notes(tmp)
    check("the appended-cell shape is reported as a WARNING, never a failed run",
          "one more cell" in (notes.get("artifacts/M20_formatting.md") or [""])[0],
          str(notes))
    check("a second table is parsed against ITS OWN header",
          [r.get("disposition") for r in
           nb.parse_markdown_table(art / "M19_length.md")] == ["OK — inside the 172-word cap"],
          str(nb.parse_markdown_table(art / "M19_length.md")))
    check("both tables of a file are checked for dispositions",
          nb.artifact_quality_report(tmp) == {}, str(nb.artifact_quality_report(tmp)))
    m18 = nb.parse_markdown_table(art / "M18_caption_words.md")
    check("an escaped pipe stays inside its cell and the stray empty cell is dropped",
          m18[0]["caption"] == "Fig. 1 | Benchmarking"
          and m18[0]["disposition"] == "OK — 134 words, recorded", str(m18))
    # (d) the gate still fails what it is FOR: an undisposed row and a shifted row
    (art / "OUTLINE.md").write_text(
        "| # | heading | summary | disposition |\n|---|---|---|---|\n"
        "| 1 | Introduction | Four-step benchmark workflow |  |\n",
        encoding="utf-8")
    report = nb.artifact_quality_report(tmp)
    check("a genuinely empty disposition cell is still a problem",
          any("EMPTY" in p for p in report.get("artifacts/OUTLINE.md") or []), str(report))


# ---------------------------------------------------------------------------
# 4. the auditor stage: artifact contract, drop/add split, plan wiring
# ---------------------------------------------------------------------------


def test_audit_contract():
    print()
    print("== the auditor's artifact contract ==")
    frozen = ["F-001", "F-002", "F-003"]
    good = {"dispositions": [
        {"id": "F-001", "verdict": "confirm", "reason": "real defect", "evidence": "quote"},
        {"id": "F-002", "verdict": "drop",
         "reason": "the quoted text does not exist in base/ under any spelling",
         "evidence": "base/cnb-12-2-mainText.docx: the paragraph reads '...' (no 'X' token)"},
        {"id": "F-003", "verdict": "confirm", "reason": "real", "evidence": "quote"}],
        "adds": [{"id": "AU-001", "location": "cover letter p7", "category": 2, "check": "M20",
                  "severity": "Minor", "evidence": "'Nature Biotechnology' 5x in one letter",
                  "problem": "The journal name is repeated five times in a short passage; the "
                             "reviewer closed the row as 'no journal rule'."}]}
    check("a well-formed audit record is accepted",
          not nb.audit_artifact_problems(good, frozen), str(nb.audit_artifact_problems(good, frozen)))
    missing = dict(good, dispositions=good["dispositions"][:2])
    check("silence about a frozen id is a problem",
          any("neither confirmed nor dropped" in p
              for p in nb.audit_artifact_problems(missing, frozen)),
          str(nb.audit_artifact_problems(missing, frozen))[:200])
    bad_drop = {"dispositions": [
        {"id": "F-001", "verdict": "drop", "reason": "I disagree", "evidence": "no"}] + good["dispositions"][1:],
        "adds": []}
    probs = nb.audit_artifact_problems(bad_drop, frozen)
    check("a drop without evidence/reason is rejected",
          any("EVIDENCE" in p or "reason" in p for p in probs), str(probs)[:200])
    bad_add = dict(good, adds=[{"id": "F-999", "location": "x", "category": "two",
                                "check": "", "severity": "big", "evidence": "y",
                                "problem": "z"}])
    aprobs = nb.audit_artifact_problems(bad_add, frozen)
    check("an added finding must be AU-<n> with a category/severity/check",
          any("not AU-" in p for p in aprobs) and any("severity" in p for p in aprobs),
          str(aprobs)[:200])
    split = nb.apply_audit_to_findings(
        [{"id": i, "severity": "Minor", "category": 2} for i in frozen], good)
    check("the drop/add split keeps the rest and adds the AU- finding",
          [f["id"] for f in split["kept"]] == ["F-001", "F-003"]
          and [f["id"] for f in split["dropped"]] == ["F-002"]
          and [f["id"] for f in split["added"]] == ["AU-001"], str(split)[:200])


def test_audit_plan_wiring():
    print()
    print("== `--audit on` inserts the stage between the review and the revisers ==")
    check("the mode vocabulary is off|on with ON as the default (2026-09-22)",
          nb.AUDIT_MODES == ("off", "on") and nb.DEFAULT_AUDIT == "on")
    check("`--only audit` is an accepted stage",
          "audit" in nb.ONLY_STAGES and nb.ONLY_ALIASES.get("auditor") == "audit")
    off = type("C", (), {"cfg": {"audit": "off"}})()
    on = type("C", (), {"cfg": {"audit": "on"}})()
    check("audit_enabled follows the config", not nb.audit_enabled(off) and nb.audit_enabled(on))
    check("the round id is r<r>_audit", nb.rid_audit(2) == "r2_audit")
    check("the placeholder-lookup default is online",
          nb.DEFAULT_PLACEHOLDER_LOOKUP == "online"
          and nb.placeholder_lookup_of(off) == "online")
    check("an unknown stored lookup mode never widens to online",
          nb.placeholder_lookup_of(type("C", (), {"cfg": {"placeholder_lookup": "wat"}})())
          == "online")
    prompt = nb.audit_prompt(Path("/tmp/sb"), "r1_audit", 1)
    check("the auditor prompt names the freeze and the disposition attack",
          "audit.json" in prompt and "boilerplate" in prompt and "AU-" in prompt)


def test_collect_residuals():
    print()
    print("== collect_residuals feeds `decide --residual-gate` ==")
    state = {"runs": {
        "r1_a2_revise": {"id": "r1_a2_revise", "kind": "revise", "status": "done",
                         "residual": {"searchable_placeholders": 1, "answerable_placeholders": 1,
                                      "answered_kinds": ["preprint"],
                                      "unsourced_numbers_in_abstract_legends": 3}},
        "r1_review": {"id": "r1_review", "kind": "review", "status": "done",
                      "artifact_quality": {"artifacts/M20_formatting.md":
                                           ["96 of 191 dispositions repeat the SAME sentence"]}},
    }}
    ctx = type("C", (), {"state": state})()
    res = nb.collect_residuals(ctx)
    text = " | ".join(res["items"])
    check("an answerable marker that shipped is a residual item",
          "searchable hand-off marker" in text, text[:160])
    check("unsourced abstract/legend numbers are a residual item",
          "not proved by any shipped data table" in text, text[:200])
    check("a boilerplate review artifact is a residual item",
          "decision artifact artifacts/M20_formatting.md" in text, text[:200])


# ---------------------------------------------------------------------------
# 5. end-to-end with the stub agent: the new artifacts + the audit stage
# ---------------------------------------------------------------------------


def test_stub_round_with_audit():
    print()
    print("== stub round: provenance pack seeded, audit stage runs end to end ==")
    tmp = scratch("nbt_residual_e2e_")
    src = tmp / "src"
    make_text_corpus(src)
    root = tmp / "root"
    r = cli("setup", "--source", str(src), "--root", str(root), "--rounds", "1",
            "--judges", "1", "--rewrites", "0", "--revises", "1",
            "--audit", "on", "--placeholder-lookup", "off")
    check("setup succeeds", r.returncode == 0, (r.stderr or r.stdout)[-300:])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("setup persists audit + placeholder lookup + the strict default",
          cfg.get("audit") == "on" and cfg.get("placeholder_lookup") == "off"
          and cfg.get("strict_artifacts") is True, json.dumps(cfg)[:200])
    r = cli("run", "--root", str(root), "--only", "review",
            "--agent-cmd", json.dumps([sys.executable, str(STUB)]), "--retries", "0")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("the review stage completes",
          (state["runs"].get("r1_review") or {}).get("status") == "done",
          json.dumps(((state["runs"].get("r1_review") or {}).get("postcheck") or {})
                     .get("errors") or [])[:300])
    review = root / "runs" / "r1_review" / "review"
    for rel in ("work/PROVENANCE.json", "work/NUMBERS_LEDGER.md",
                "artifacts/NUMBERS_LEDGER.md", "artifacts/IDENTIFIERS.md",
                "artifacts/PLACEHOLDER_LOOKUP.md", "artifacts/M24_concepts.md",
                "artifacts/GLOSSARY.md"):
        check(f"the review sandbox carries {rel}", (review / rel).is_file())
    prompt = (root / "runs" / "r1_review" / "PROMPT.md").read_text(encoding="utf-8")
    check("the review prompt carries the decision-artifact mandate",
          "DECISION-ARTIFACT MANDATE" in prompt and "tier" in prompt)
    check("the audit stage did not run before it was asked for",
          not (root / "runs" / "r1_audit").exists())
    r = cli("run", "--root", str(root), "--only", "audit",
            "--agent-cmd", json.dumps([sys.executable, str(STUB)]), "--retries", "0")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("the auditor stage completes",
          (state["runs"].get("r1_audit") or {}).get("status") == "done",
          json.dumps(((state["runs"].get("r1_audit") or {}).get("postcheck") or {})
                     .get("errors") or [])[:300])
    audit = root / "runs" / "r1_audit"
    check("the auditor wrote its artifact", (audit / "audit" / "audit.json").is_file())
    aprompt = (audit / "PROMPT.md").read_text(encoding="utf-8")
    check("the auditor sandbox has the frozen review and the evidence pack",
          (audit / "review" / "findings.json").is_file()
          and (audit / "work" / "NUMBERS_LEDGER.md").is_file())
    arec = state["runs"].get("r1_audit") or {}
    check("the audit run is recorded as done with its effect",
          arec.get("status") == "done" and (arec.get("audit_effect") or {}).get("added") == 0,
          json.dumps(arec.get("audit_effect") or {})[:200])
    rrec = state["runs"].get("r1_review") or {}
    check("the compliant stub leaves NO artifact-quality problem (strict mode passed)",
          rrec.get("artifact_quality") == {}
          and (rrec.get("postcheck") or {}).get("ok") is True,
          json.dumps(rrec.get("artifact_quality") or {})[:200])
    ctx = type("C", (), {"state": state, "cfg": cfg,
                         "run": lambda self, rid: (state["runs"] or {}).get(rid)})()
    # A compliant round leaves NO gating residual but still RECORDS the list; the
    # detector itself is exercised by test_agent_consistency_2026_0922 and by the
    # injected fixture below.
    res = nb.collect_residuals(ctx)
    check("a compliant round records an empty residual list",
          res.get("gating") == [] and res.get("count") == len(res.get("items") or []),
          str(res)[:200])
    broken = dict(state)
    broken["runs"] = dict(state["runs"])
    broken["runs"]["r1_review"] = dict(broken["runs"]["r1_review"],
                                       artifact_quality={"artifacts/M20_formatting.md":
                                                         ["96 of 200 dispositions repeat the "
                                                          "SAME sentence"]})
    res2 = nb.collect_residuals(type("C", (), {"state": broken, "cfg": cfg})())
    check("an injected boilerplate artifact is picked up as a GATING residual",
          any("decision artifact" in it for it in res2["gating"]), str(res2["gating"])[:200])
    check("`decide --residual-gate` is a documented flag",
          "--residual-gate" in cli("decide", "--help").stdout)


def test_seeded_paths_cover_every_new_artifact():
    print()
    print("== every seeded file is declared as an INPUT (or the leftover guard pauses "
          "the run) ==")
    tmp = scratch("nbt_residual_seed_")
    src = tmp / "src"
    make_text_corpus(src)
    ctx = type("C", (), {"cfg": {"placeholder_lookup": "off"}})()
    for where, sub in (("review", "review"), ("audit", None), ("stage", None)):
        sb = tmp / f"run_{where}"
        sb.mkdir()
        nb.seed_evidence_pack(ctx, sb, src, where)
        seeded = {p.relative_to(sb).as_posix() for p in nb.seeded_evidence_paths(sb)}
        written = {p.relative_to(sb).as_posix() for p in sb.rglob("*")
                   if p.is_file() and p.name != "PROMPT.md" and not p.name.endswith(".py")}
        missing = sorted(written - seeded)
        check(f"{where}: every seeded file is in seeded_evidence_paths()", not missing,
              str(missing))


def main() -> int:
    try:
        test_sentence_bar_tiers()
        test_repetition_and_gloss_and_concepts()
        test_latex_siunitx_rule()
        test_placeholder_kinds_and_plan()
        test_lookup_batch_offline_and_numbers()
        test_gene_symbol_ledger()
        test_disposition_detectors()
        test_markdown_table_roundtrip()
        test_delivered_table_shapes()
        test_audit_contract()
        test_audit_plan_wiring()
        test_collect_residuals()
        test_seeded_paths_cover_every_new_artifact()
        test_stub_round_with_audit()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("all residual-audit checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

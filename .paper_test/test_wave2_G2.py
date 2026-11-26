#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 2, group G2 (run 20261115-220228).

One check block per re-validated candidate. Hermetic: temp dirs only, no
network, no Word, no agent runs.

Run:  python3 -B .paper_test/test_wave2_G2.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402

FAILS = []


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def tmpdir(tag: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"fb2g2_{tag}_"))


def pair(tag: str, base_text: str, cand_text: str):
    root = tmpdir(tag)
    base, cand = root / "base", root / "candidate"
    base.mkdir()
    cand.mkdir()
    (base / "paper.md").write_text(base_text, encoding="utf-8")
    (cand / "paper.md").write_text(cand_text, encoding="utf-8")
    return base, cand


# ---------------------------------------------------------------------------
# C011 -- the MCP entry's command is a top-level key, not a line inside args
# ---------------------------------------------------------------------------
def c011() -> None:
    print("\n== C011: a `command` line inside a multiline args string is not the executable ==")
    cfg = tmpdir("c011") / "config.toml"
    cfg.write_text(
        '[mcp_servers.x]\n'
        'args = ["""\ncommand = "evil"\n[looks-like-a-header]\n"""]\n'
        'command = "node"\n',
        encoding="utf-8")
    saved = pp.codex_config_path
    pp.codex_config_path = lambda: cfg
    try:
        check("C011 the TOML command wins over the embedded line",
              pp.mcp_server_spec("x").get("command") == "node",
              str(pp.mcp_server_spec("x"))[:200])
        check("C011 the args value is read from the real array",
              pp.mcp_server_spec("x").get("args") == ['command = "evil"\n[looks-like-a-header]\n'],
              str(pp.mcp_server_spec("x"))[:200])
        cfg.write_text(
            '[mcp_servers.y]\n'
            'command = "npx"\n'
            'args = ["-y", "server.js"]\n'
            'cwd = "/tmp/work"\n'
            'env = { A = "b" }\n\n'
            '[mcp_servers.z]\n'
            'command = "other"\n',
            encoding="utf-8")
        spec_y = pp.mcp_server_spec("y")
        check("C011 an ordinary entry still reads command/args/cwd/env",
              spec_y.get("command") == "npx" and spec_y.get("args") == ["-y", "server.js"]
              and spec_y.get("cwd") == "/tmp/work" and spec_y.get("env") == {"A": "b"},
              str(spec_y)[:240])
        check("C011 the next entry is not mixed in",
              pp.mcp_server_spec("z").get("command") == "other",
              str(pp.mcp_server_spec("z"))[:120])
    finally:
        pp.codex_config_path = saved


# ---------------------------------------------------------------------------
# C013 -- "pending"/"did nothing" is not a prior-proposal disposition
# ---------------------------------------------------------------------------
def c013() -> None:
    print("\n== C013: a note that says the prior proposal was NOT done is not a disposition ==")
    for note in ("prior proposal M37: pending execution in the next round",
                 "The prior round proposed M37 but this round did nothing about it.",
                 "prior proposal M37: deferred to the next round",
                 "prior proposal M37: not re-probed this round"):
        check(f"C013 refused: {note[:38]!r}",
              pp.prior_proposal_dispositioned("M37", "", note) is False, note)
    check("C013 the documented note form still disposes",
          pp.prior_proposal_dispositioned("M37", "",
                                          "prior proposal M37: no instances in base/") is True)
    check("C013 a probe row still disposes",
          pp.prior_proposal_dispositioned(
              "M37", "| M37 | probe | base/ | no anomalies -- checked: base/ |", "") is True)
    check("C013 a probe row that says pending does not",
          pp.prior_proposal_dispositioned(
              "M37", "| M37 | probe | base/ | pending |", "") is False)


# ---------------------------------------------------------------------------
# C014 -- an added finding's own cells are pinned by the repair guard
# ---------------------------------------------------------------------------
def c014() -> None:
    print("\n== C014: a repair may not rewrite an auditor's added finding ==")
    sb = tmpdir("c014")
    (sb / "audit").mkdir(parents=True)
    audit = {"dispositions": [{"id": "F-001", "verdict": "confirm", "reason": "r",
                               "evidence": "e"}],
             "adds": [{"id": "AU-001", "location": "x", "evidence": "ORIGINAL EVIDENCE",
                       "severity": "minor"}]}
    path = sb / "audit" / "audit.json"
    path.write_text(json.dumps(audit), encoding="utf-8")
    guard = pp.snapshot_repair_guard(sb, {"kind": "audit", "round": 1})
    audit["adds"][0]["evidence"] = "FORGED EVIDENCE"
    audit["adds"][0]["severity"] = "fatal"
    path.write_text(json.dumps(audit), encoding="utf-8")
    probs = pp._repair_audit_problems(sb, guard)
    check("C014 rewriting the added finding's evidence/severity is rejected",
          any("rewrote the auditor's added finding" in p and "AU-001" in p for p in probs),
          str(probs)[:240])
    audit["adds"][0]["evidence"] = "ORIGINAL EVIDENCE"
    audit["adds"][0]["severity"] = "minor"
    audit["dispositions"].append({"id": "F-002", "verdict": "confirm",
                                  "reason": "checked", "evidence": "main.md:3"})
    path.write_text(json.dumps(audit), encoding="utf-8")
    check("C014 an untouched add plus an added confirm passes",
          pp._repair_audit_problems(sb, guard) == [],
          str(pp._repair_audit_problems(sb, guard))[:200])
    audit["adds"].append({"id": "AU-2"})
    path.write_text(json.dumps(audit), encoding="utf-8")
    check("C014 inventing an AU id is still rejected",
          any("it invented finding(s) AU-2" in p
              for p in pp._repair_audit_problems(sb, guard)))
    audit["adds"] = [{"id": "AU-2"}]
    path.write_text(json.dumps(audit), encoding="utf-8")
    check("C014 deleting an existing AU finding is rejected",
          any("DELETED the auditor's added finding(s) AU-001" in p
              for p in pp._repair_audit_problems(sb, guard)),
          str(pp._repair_audit_problems(sb, guard))[:240])


# ---------------------------------------------------------------------------
# C015 -- the seeded table needs its OWN disposition column
# ---------------------------------------------------------------------------
def c015() -> None:
    print("\n== C015: a decoy table does not dispose the seeded rows ==")
    rd = tmpdir("c015") / "guided_review"
    (rd / "artifacts").mkdir(parents=True)
    art = rd / "artifacts" / "M18_caption_words.md"
    art.write_text(
        "| document | caption | words |\n|---|---|---|\n"
        "| a.docx | fig1 | 10 |\n| a.docx | fig2 | 11 |\n\n"
        "| item | disposition |\n|---|---|\n| dummy | OK - a reason for this row |\n",
        encoding="utf-8")
    report = pp.artifact_quality_report(
        rd, require_files=False,
        seeded_row_counts={"artifacts/M18_caption_words.md": 2})
    probs = report.get("artifacts/M18_caption_words.md") or []
    check("C015 the undisposed seeded block is reported",
          any("no `disposition` column" in p for p in probs), str(probs)[:240])
    art.write_text(
        "| document | caption | words | disposition |\n|---|---|---|---|\n"
        "| a.docx | fig1 | 10 | OK - within the limit |\n"
        "| a.docx | fig2 | 11 | OK - within the limit |\n",
        encoding="utf-8")
    check("C015 a properly disposed table still passes",
          pp.artifact_quality_report(
              rd, require_files=False,
              seeded_row_counts={"artifacts/M18_caption_words.md": 2}) == {},
          str(pp.artifact_quality_report(rd, require_files=False))[:200])


# ---------------------------------------------------------------------------
# C017 -- a standard unit outside the old table is still part of the fact
# ---------------------------------------------------------------------------
def c017() -> None:
    print("\n== C017: a same-number unit change is reported for standard units ==")
    body = "# Diet\n\nThe protocol supplied {value} each day for eight weeks.\n\n" \
           "Another paragraph of ordinary prose sits here.\n"
    for base_value, cand_value in (("2500 kcal", "2500 kJ"), ("55 in", "55 cm"),
                                   ("760 Torr", "760 kPa"), ("100 IU", "100 mg")):
        base, cand = pair("c017", body.format(value=base_value),
                          body.format(value=cand_value))
        probs = pp.fact_preservation_problems(base, cand, "revise")
        check(f"C017 {base_value} -> {cand_value} is reported",
              any("change its UNIT" in p for p in probs), str(probs)[:160])
    base, cand = pair("c017b", body.format(value="55 mg"), body.format(value="55 mL"))
    check("C017 the control 55 mg -> 55 mL is still reported",
          any("change its UNIT" in p for p in pp.fact_preservation_problems(base, cand, "revise")))
    base, cand = pair("c017c", body.format(value="55 of the animals"),
                      body.format(value="55 in the cohort"))
    check("C017 an ordinary following word is still not invented as a unit",
          pp.fact_preservation_problems(base, cand, "revise") == [],
          str(pp.fact_preservation_problems(base, cand, "revise"))[:200])
    auth = "# Author hand-off\n\nCORRECTED MEASUREMENT: 55 cm (the printed unit was wrong)\n"
    base, cand = pair("c017d", body.format(value="55 in"), body.format(value="55 cm"))
    (cand / "README-AUTHOR-TO-COMPLETE.md").write_text(auth, encoding="utf-8")
    check("C017 the documented recorded correction still passes",
          pp.fact_preservation_problems(base, cand, "revise") == [],
          str(pp.fact_preservation_problems(base, cand, "revise"))[:240])


# ---------------------------------------------------------------------------
# C018 -- a lowercase-starting sentence is a new content unit
# ---------------------------------------------------------------------------
def c018() -> None:
    print("\n== C018: a lowercase-starting sentence is split, so its deletion is seen ==")
    base, cand = pair(
        "c018",
        "# Results\n\nThe difference between arms was significant. "
        "p < 0.05 for every cohort. The dose was 55 mg in each arm.\n\n"
        "Another paragraph of ordinary words follows here.\n",
        "# Results\n\nThe difference between arms was significant. "
        "The dose was 55 mg in each arm.\n\n"
        "Another paragraph of ordinary words follows here.\n")
    texts = [u["text"] for u in pp._content_unit_sentences(base)]
    check("C018 the p-value sentence is its own unit",
          "p < 0.05 for every cohort." in texts, str(texts)[:200])
    check("C018 the strict no-deletion gate sees it",
          bool(pp.content_edit_problems(None, base, cand, "revise",
                                        insertions_allowed=False, deletions_allowed=False)),
          str(pp.content_edit_problems(None, base, cand, "revise",
                                       insertions_allowed=False,
                                       deletions_allowed=False))[:160])
    check("C018 the D8 fact gate sees it",
          bool(pp.fact_preservation_problems(base, cand, "revise")))
    check("C018 'et al.' still continues the unit",
          pp._content_sentence_parts(
              "The method follows Smith et al. The results were significant.") ==
          ["The method follows Smith et al.", "The results were significant."])
    check("C018 a lowercase continuation after 'et al.' still merges",
          pp._content_sentence_parts(
              "The method of Smith et al. was used for all assays.") ==
          ["The method of Smith et al. was used for all assays."])


# ---------------------------------------------------------------------------
# C059 -- a one-letter group label is not a unit
# ---------------------------------------------------------------------------
def c059() -> None:
    print("\n== C059: a letter that labels a group is not read as a unit ==")
    base, cand = pair(
        "c059",
        "# X\n\nWe included 55 A participants in the cohort.\n\n"
        "Another paragraph of ordinary words follows here.\n",
        "# X\n\nWe included 55 participants in the cohort.\n\n"
        "Another paragraph of ordinary words follows here.\n")
    check("C059 dropping the group label is not a unit change",
          pp.fact_preservation_problems(base, cand, "revise") == [],
          str(pp.fact_preservation_problems(base, cand, "revise"))[:200])
    base, cand = pair(
        "c059b",
        "# X\n\nWe held the cell at 5 V across the resistor for an hour.\n\n"
        "Another paragraph of ordinary words follows here.\n",
        "# X\n\nWe held the cell at 5 V across the load for an hour.\n\n"
        "Another paragraph of ordinary words follows here.\n")
    check("C059 a real one-letter unit before a unit reading is kept",
          pp.fact_preservation_problems(base, cand, "revise") == [],
          str(pp.fact_preservation_problems(base, cand, "revise"))[:200])


# ---------------------------------------------------------------------------
# C061 -- a standalone short measurement is a content unit
# ---------------------------------------------------------------------------
def c061() -> None:
    print("\n== C061: a standalone `50 mg.` paragraph is a content unit ==")
    base, cand = pair("c061", "# Dose\n\n50 mg.\n\nCells were counted twice.\n",
                      "# Dose\n\nCells were counted twice.\n")
    check("C061 the dose line is a unit",
          "50 mg." in [u["text"] for u in pp._content_unit_sentences(base)],
          str([u["text"] for u in pp._content_unit_sentences(base)])[:160])
    check("C061 the strict gate reports its deletion",
          bool(pp.content_edit_problems(None, base, cand, "revise",
                                        insertions_allowed=False, deletions_allowed=False)))
    check("C061 the fact gate reports it",
          bool(pp.fact_preservation_problems(base, cand, "revise")))
    check("C061 the deletion audit seeds a row",
          any("50 mg" in str(r.get("paragraph")) for r in pp.deletion_audit_rows(base, cand)),
          str(pp.deletion_audit_rows(base, cand))[:160])


# ---------------------------------------------------------------------------
# C062 -- a deleted short claim still seeds a deletion-audit row
# ---------------------------------------------------------------------------
def c062() -> None:
    print("\n== C062: a short deleted claim seeds a deletion-audit row ==")
    base_text = ("# Dosing\n\nDose was 55 mg in total.\n\n"
                 "| item | dose |\n|---|---|\n| drug | 55 mg |\n\n"
                 "The cohort comprised 137 patients in total this year.\n")
    cand_text = ("# Dosing\n\n"
                 "| item | dose |\n|---|---|\n| drug | 55 mg |\n\n"
                 "The cohort comprised 137 patients in total this year.\n")
    base, cand = pair("c062", base_text, cand_text)
    rows = pp.deletion_audit_rows(base, cand)
    check("C062 the 24-character claim is seeded",
          any("Dose was 55 mg in total." in str(r.get("paragraph")) for r in rows),
          str(rows)[:200])
    check("C062 a bare heading is still not a row",
          pp._deleted_para_candidate("# Results") == "")


# ---------------------------------------------------------------------------
# C063 -- a section word alone is not a deletion disposition
# ---------------------------------------------------------------------------
def c063() -> None:
    print("\n== C063: `OK -- <section word>` filler is refused ==")
    for bad in ("OK \u2014 x methods", "OK \u2014 no results", "OK \u2014 x"):
        check(f"C063 refused: {bad!r}",
              pp._deletion_disposition_ok(bad) is False, bad)
    for good in ("OK \u2014 moved to Methods", "OK \u2014 merged into Results",
                 "OK \u2014 now in Table 2", "OK \u2014 duplicate; no fact lost",
                 "manual-required", "fact removed \u2014 RP-12"):
        check(f"C063 accepted: {good!r}",
              pp._deletion_disposition_ok(good) is True, good)


# ---------------------------------------------------------------------------
# C066 -- a claimed pure deletion must actually be gone
# ---------------------------------------------------------------------------
def c066() -> None:
    print("\n== C066: a pure-deletion claim is checked against the target ==")
    sb = tmpdir("c066")
    target, prev = sb / "target", sb / "previous_package"
    target.mkdir()
    prev.mkdir()
    (target / "paper.md").write_text("# Results\nThe sentence is still here.\n",
                                     encoding="utf-8")
    (prev / "paper.md").write_text("# Results\nThe sentence is still here.\n",
                                   encoding="utf-8")
    rows = [{"id": "R1-1", "changes": [{"file": "paper.md", "operation": "edit",
                                        "location": "Results",
                                        "before": "The sentence is still here."}]}]
    probs = pp._response_change_span_problems(sb, target, rows)
    check("C066 a deletion that did not happen is reported",
          any("STILL PRESENT" in p for p in probs), str(probs)[:240])
    (target / "paper.md").write_text("# Results\nA different sentence now.\n",
                                     encoding="utf-8")
    check("C066 a real deletion passes",
          pp._response_change_span_problems(sb, target, rows) == [],
          str(pp._response_change_span_problems(sb, target, rows))[:200])


# ---------------------------------------------------------------------------
# C067 -- every response block carries a **Response:** answer
# ---------------------------------------------------------------------------
def c067() -> None:
    print("\n== C067: a letter block must answer, not only quote and change ==")
    sb = tmpdir("c067")
    (sb / "target").mkdir()
    (sb / "target" / "paper.md").write_text("# Results\nNew text here.\n", encoding="utf-8")
    (sb / "response").mkdir()
    (sb / "response" / "response_map.json").write_text(json.dumps({"rows": [{
        "id": "R1-1", "status": "addressed", "response": "done",
        "changes": [{"file": "paper.md", "location": "Results",
                     "before": "Old text here.", "after": "New text here."}]}]}),
        encoding="utf-8")
    letter = sb / "response" / "RESPONSE_TO_REVIEWERS.md"
    letter.write_text(
        "# Response\n\n## R1-1 \u2014 units\n\n**Comment:** \"Please fix the units.\"\n\n"
        "**Changes:** paper.md:Results \u2014 old -> new\n", encoding="utf-8")
    errs = pp.response_local_problems(sb, sb / "target")
    check("C067 a block with no **Response:** line fails",
          any("no non-empty **Response:**" in e for e in errs), str(errs)[:240])
    letter.write_text(
        "# Response\n\n## R1-1 \u2014 units\n\n**Comment:** \"Please fix the units.\"\n\n"
        "**Response:** We fixed the units in Results.\n\n"
        "**Changes:** paper.md:Results \u2014 old -> new\n", encoding="utf-8")
    errs = pp.response_local_problems(sb, sb / "target")
    check("C067 a block with the answer passes this check",
          not any("Response" in e for e in errs), str(errs)[:240])
    letter.write_text(
        "# Response\n\n## R1-1\n\n**Comment:** \"Please fix.\"\n\n**Response:**\n\n"
        "**Changes:** paper.md:Results\n", encoding="utf-8")
    errs = pp.response_local_problems(sb, sb / "target")
    check("C067 an empty **Response:** marker does not count",
          any("no non-empty **Response:**" in e for e in errs), str(errs)[:200])


# ---------------------------------------------------------------------------
# C068 -- an unreadable container is UNVERIFIED, not a silent pass
# ---------------------------------------------------------------------------
def c068() -> None:
    print("\n== C068: an unreadable package file fails the span check ==")
    sb = tmpdir("c068")
    target, prev = sb / "target", sb / "previous_package"
    target.mkdir()
    prev.mkdir()
    (target / "paper.docx").write_bytes(b"not a zip")
    (prev / "paper.docx").write_bytes(b"also not a zip")
    rows = [{"id": "R1-1", "changes": [{
        "file": "paper.docx", "operation": "edit", "location": "Section 9: Results",
        "before": "invented before span", "after": "invented after span"}]}]
    check("C068 the extractor still returns no text",
          pp._response_file_text(target / "paper.docx") is None)
    probs = pp._response_change_span_problems(sb, target, rows)
    check("C068 an unverifiable target file is an error, not a pass",
          any("UNVERIFIED" in p and "target/paper.docx" in p for p in probs),
          str(probs)[:240])
    check("C068 an unverifiable pre-image file is an error too",
          any("UNVERIFIED" in p and "previous_package/paper.docx" in p for p in probs),
          str(probs)[:240])


# ---------------------------------------------------------------------------
# C069 -- an unreadable file fails the scoped scope guard
# ---------------------------------------------------------------------------
def c069() -> None:
    print("\n== C069: the scope guard fails closed on an unreadable file ==")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("[skip] C069 chmod 000 is not enforced for root")
        return
    sb = tmpdir("c069")
    base, rev = sb / "base", sb / "revised"
    base.mkdir()
    rev.mkdir()
    (base / "paper.md").write_text("the original sentence with 55 mg.\n", encoding="utf-8")
    (rev / "paper.md").write_text("a completely rewritten manuscript with 95 mg.\n",
                                  encoding="utf-8")
    os.chmod(base / "paper.md", 0o000)
    os.chmod(rev / "paper.md", 0o000)
    try:
        problems = pp.scoped_scope_problems(None, sb, rev)
    finally:
        os.chmod(base / "paper.md", 0o644)
        os.chmod(rev / "paper.md", 0o644)
    check("C069 an unreadable document is reported, not treated as absent",
          any("cannot be read" in p for p in problems), str(problems)[:240])


# ---------------------------------------------------------------------------
# C158 -- a judge's X id resolves against the row's own side
# ---------------------------------------------------------------------------
def c158() -> None:
    print("\n== C158: a cited X id resolves against the row's own side ==")
    sb = tmpdir("c158")
    dd = sb / "judge_review" / "discovery"
    dd.mkdir(parents=True)
    head = "| # | candidate | disposition |\n|---|---|---|\n"

    def rows(mark_first: bool) -> str:
        body = []
        for i in range(1, 6):
            body.append(f"| {i} | class {i} | "
                        + (f"finding - X-{i:03d} (category 2, Major): p{i}: `evidence`"
                           if i == 1 and mark_first
                           else f"clean - checked: p{i}")
                        + " |")
        return head + "\n".join(body) + "\n"

    (dd / "target.md").write_text(rows(True), encoding="utf-8")
    (dd / "v1.md").write_text(rows(False), encoding="utf-8")
    (sb / "scores.json").write_text(json.dumps({"comparisons": [{
        "opponent_label": "v1",
        "resolved": [{"check": "X-001", "tier": "consistency", "severity": "minor",
                      "evidence": "e"}],
        "introduced": []}]}), encoding="utf-8")
    errs, warns = pp.judge_discovery_problems(sb, {"kind": "judge", "label_map": {"v1": 1}})
    check("C158 an id defined only on the other side warns",
          any("X-001" in w and "v1 side" in w for w in warns), str(warns)[:240])
    # The counterpart (target) must dispose the SAME candidate clean for the
    # pair to be decidable (F90-20261126): put the finding on v1 only, so this
    # still tests the F212 own-side id resolution without an undecidable pair.
    (dd / "target.md").write_text(rows(False), encoding="utf-8")
    (dd / "v1.md").write_text(rows(True), encoding="utf-8")
    errs, warns = pp.judge_discovery_problems(sb, {"kind": "judge", "label_map": {"v1": 1}})
    check("C158 an id defined on the row's own side passes",
          not warns and not errs, f"{errs} {warns}")


# ---------------------------------------------------------------------------
# C159 -- a location may not name a same-named file in another directory
# ---------------------------------------------------------------------------
def c159() -> None:
    print("\n== C159: a file-line locator must name the row's own path ==")
    check("C159 b/main.md is not a/main.md",
          pp._response_same_file("b/main.md", "a/main.md") is False)
    check("C159 a bare filename still names the same document",
          pp._response_same_file("main.md", "a/main.md") is True)
    check("C159 the target/ prefix is still accepted",
          pp._response_same_file("target/paper.md", "paper.md") is True)
    problem = pp._response_location_problem(
        "R1-1", "a/main.md", "b/main.md:12", None, None, None,
        "# Results\nSome after text.\n")
    check("C159 the wrong-directory locator is reported",
          problem is not None and "not this row's file" in problem, str(problem)[:200])
    ok = pp._response_location_problem(
        "R1-1", "a/main.md", "a/main.md:12", None, None, None,
        "# Results\nSome after text.\n")
    check("C159 the row's own locator still resolves", ok is None, str(ok)[:160])


def c007_id_list_is_not_a_disposition():
    print("\n== C007: an id-only revision ledger is not a disposition ==")
    import json as _json
    import tempfile as _tempfile

    def run(ledger):
        pkg = Path(_tempfile.mkdtemp())
        (pkg / "revision_report.json").write_text(_json.dumps(ledger), encoding="utf-8")
        errs, _warns = pp.revision_ledger_problems(
            pkg, ["F-001", "F-002"], 2, rel="revised/revision_report.json")
        return errs

    errs = run(["F-001", "F-002"])
    check("C007 a bare id list names but does not dispose",
          any("without a VERDICT" in e for e in errs), str(errs[:1]))
    errs = run({"finding_ids": ["F-001", "F-002"]})
    check("C007 an id list under a key names but does not dispose",
          any("without a VERDICT" in e for e in errs), str(errs[:1]))
    rows = [{"id": "F-001", "verdict": "confirmed", "rationale": "r", "evidence": "e"},
            {"id": "F-002", "verdict": "false-positive", "rationale": "r", "evidence": "e"}]
    check("C007 verdict rows still pass", run(rows) == [])
    check("C007 a list alongside verdict rows still passes",
          run({"finding_ids": ["F-001", "F-002"], "rows": rows}) == [])


def main() -> int:
    c011()
    c013()
    c014()
    c015()
    c017()
    c018()
    c059()
    c061()
    c062()
    c063()
    c066()
    c067()
    c068()
    c069()
    c158()
    c159()
    c007_id_list_is_not_a_disposition()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    if FAILS:
        for f in FAILS:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

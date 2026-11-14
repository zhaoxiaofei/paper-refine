#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression checks for the 2026-11-14 fix_bugs round, group K (postchecks/gates).

One check per finding this group confirmed AND fixed:
  F111 seeded M20 rows cannot be deleted down to the header
  F112 a negated count disposition is not a real coverage disposition
  F113 a malformed MCP `args` value is unreadable, never an empty argv
  F114 a repair may not rewrite MANUAL_STEPS.md outside its own package
  F115 completion_signal_exists only accepts a signal relocation would adopt
  F116 a note that says the prior proposal was NOT re-probed is not a disposition
  F117 the integration ledger's own `dropped -- not in force` row reconciles an id
  F118 the raw-data advisory names ADDED files too
  F119 an existing but EMPTY pristine raw_data/ does not exempt added files
  F120 a table-form / unreadable prior-audit record is not an empty handoff
  F122 FACT_VERIFICATION rejects an impossible checked_at date
  F123 a scoped review that really disposes an out-of-scope check is accepted
  F124 the FMT-CL1 survival shortcut does not accept a DIFFERENT document's row
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)

spec = importlib.util.spec_from_file_location("paperp_k", WS / "paper_pipeline.py")
pp = importlib.util.module_from_spec(spec)
sys.modules["paperp_k"] = pp
spec.loader.exec_module(pp)

FAILS = []
_TMP = []


def scratch(prefix):
    p = Path(tempfile.mkdtemp(prefix=prefix))
    _TMP.append(p)
    return p


def check(name, ok, detail=""):
    if ok:
        print(f"[ok ] {name}")
    else:
        print(f"[FAIL] {name}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(name)


# ---------------------------------------------------------------- F111
M20_HEADER = ("| # | rule | tier | severity | location | evidence | fix kind | disposition |\n"
              "|---|---|---|---|---|---|---|---|\n")


def _decision_tables(rd):
    for rel in pp.DECISION_ARTIFACTS:
        p = rd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("| rule | disposition |\n|---|---|\n| x | F-001: restyled |\n",
                     encoding="utf-8")


def _m20_row(i, rule="FMT-S1", location="body"):
    return (f"| {i} | {rule} | finding | high | {location} | e{i} | mechanical | "
            f"F-001: restyle |\n")


def test_f111_seeded_m20_rows_cannot_be_deleted():
    rd = scratch("k111_") / "guided_review"
    _decision_tables(rd)
    work = rd / "work"
    work.mkdir()
    (work / "FORMAT_SCAN.json").write_text(json.dumps(
        {"rows": [{"rule": "FMT-S1", "tier": "finding", "severity": "high",
                   "location": "body", "evidence": "e", "fix": "mechanical"}]}),
        encoding="utf-8")
    m20 = rd / "artifacts" / "M20_formatting.md"
    m20.write_text(M20_HEADER, encoding="utf-8")
    rep = pp.artifact_quality_report(rd, require_files=True)
    check("F111 a code-seeded M20 table emptied to its header FAILS",
          any("code-seeded row" in p for p in (rep.get("artifacts/M20_formatting.md") or [])),
          str(rep)[:240])
    m20.write_text(M20_HEADER + _m20_row(1), encoding="utf-8")
    rep = pp.artifact_quality_report(rd, require_files=True)
    check("F111 the seeded row being present and disposed PASSES", not rep, str(rep)[:240])
    # R02: a SET of rule names collapsed duplicate rows, so deleting one of
    # several same-rule seeded rows was invisible. Count them instead.
    rd3 = scratch("k111c_") / "guided_review"
    _decision_tables(rd3)
    (rd3 / "work").mkdir()
    dup = [{"rule": "FMT-T8d", "tier": "finding", "severity": "medium",
            "location": f"a.docx:{i}", "evidence": f"e{i}", "fix": "mechanical"}
           for i in (1, 2, 3)]
    (rd3 / "work" / "FORMAT_SCAN.json").write_text(json.dumps({"rows": dup}), encoding="utf-8")
    m20 = rd3 / "artifacts" / "M20_formatting.md"
    m20.write_text(M20_HEADER + _m20_row(1, "FMT-T8d", "a.docx:1"), encoding="utf-8")
    rep = pp.artifact_quality_report(rd3, require_files=True)
    check("F111 deleting 2 of 3 duplicate-rule seeded rows FAILS",
          any("2 of the 3 code-seeded row(s)" in p
              for p in (rep.get("artifacts/M20_formatting.md") or [])), str(rep)[:300])
    m20.write_text(M20_HEADER + "".join(
        _m20_row(i, "FMT-T8d", f"a.docx:{i}") for i in (1, 2, 3)), encoding="utf-8")
    check("F111 all three duplicate-rule rows disposed PASSES",
          not pp.artifact_quality_report(rd3, require_files=True),
          str(pp.artifact_quality_report(rd3, require_files=True))[:240])
    # R02: a missing seed file is UNVERIFIED, not an empty seed.
    (rd3 / "work" / "FORMAT_SCAN.json").unlink()
    m20.write_text(M20_HEADER, encoding="utf-8")
    rep = pp.artifact_quality_report(rd3, require_files=True)
    check("F111 a missing FORMAT_SCAN.json FAILS as unverified",
          any("missing or unreadable" in p
              for p in (rep.get("artifacts/M20_formatting.md") or [])), str(rep)[:300])
    # R02: the postcheck re-derives the seed from the read-only base/, so an
    # emptied session-writable scan file cannot switch the pin off.
    (rd3 / "work" / "FORMAT_SCAN.json").write_text(json.dumps({"rows": []}), encoding="utf-8")
    rep = pp.artifact_quality_report(rd3, require_files=True, m20_seed_rows=dup)
    check("F111 an emptied session scan cannot erase the re-derived seed",
          any("code-seeded row" in p
              for p in (rep.get("artifacts/M20_formatting.md") or [])), str(rep)[:300])
    # The documented header-only allowance stays for an explicit EMPTY seed.
    rd4 = scratch("k111d_") / "guided_review"
    _decision_tables(rd4)
    (rd4 / "work").mkdir()
    (rd4 / "work" / "FORMAT_SCAN.json").write_text(json.dumps({"rows": []}), encoding="utf-8")
    (rd4 / "artifacts" / "M20_formatting.md").write_text(M20_HEADER, encoding="utf-8")
    check("F111 a header-only table with an explicit empty seed is still accepted",
          pp.artifact_quality_report(rd4, require_files=True) == {},
          str(pp.artifact_quality_report(rd4, require_files=True))[:200])
    # The POSTCHECK path must use the seed it re-derives from base/, not the
    # session's scan file: an emptied scan there cannot switch the pin off.
    class _Ctx:
        cfg = {}

    sb = scratch("k111e_") / "sb"
    (sb / "base").mkdir(parents=True)
    rd5 = sb / "guided_review"
    _decision_tables(rd5)
    (rd5 / "work").mkdir()
    (rd5 / "work" / "FORMAT_SCAN.json").write_text(json.dumps({"rows": []}),
                                                   encoding="utf-8")
    (rd5 / "artifacts" / "M20_formatting.md").write_text(M20_HEADER, encoding="utf-8")
    orig_scan, orig_policy = pp.scan_format_in_sources, pp.format_policy_of
    pp.scan_format_in_sources = lambda sources, policy=None: {"rows": dup}
    pp.format_policy_of = lambda ctx: {}
    try:
        rec = {}
        pp.check_artifact_quality(_Ctx(), rec, sb, [], [])
    finally:
        pp.scan_format_in_sources = orig_scan
        pp.format_policy_of = orig_policy
    check("F111 the postcheck re-derives the M20 seed from base/, ignoring an emptied scan",
          any("code-seeded row" in p for p in
              ((rec.get("artifact_quality") or {}).get("artifacts/M20_formatting.md") or [])),
          str(rec)[:300])


# ---------------------------------------------------------------- F112
def test_f112_negated_count_disposition():
    for value in ("0 findings -- not checked", "0 findings; the sweep did not run",
                  "0 findings, the check was not reviewed"):
        check(f"F112 {value!r} is refused", not pp._coverage_disposition_ok(value))
    for value in ("0 findings", "3 findings", "2 findings; none critical"):
        check(f"F112 {value!r} is still a real disposition", pp._coverage_disposition_ok(value))
    check("F112 a clean basis that negates the check is still refused",
          not pp._coverage_disposition_ok("clean -- basis: artifacts/M1.md not checked"))


# ---------------------------------------------------------------- F113
def test_f113_malformed_mcp_args():
    cfg = scratch("k113_") / "config.toml"
    real = pp.codex_config_path
    pp.codex_config_path = lambda: cfg
    try:
        cfg.write_text('[mcp_servers.docx]\ncommand = "node"\nargs = ["server.js"]\n',
                       encoding="utf-8")
        check("F113 a valid args array is still read",
              pp.mcp_server_spec("docx") == {"command": "node", "args": ["server.js"]},
              str(pp.mcp_server_spec("docx")))
        for label, text in (
                ("unterminated array",
                 '[mcp_servers.docx]\ncommand = "node"\nargs = ["server.js"\n'),
                ("args is a string",
                 '[mcp_servers.docx]\ncommand = "node"\nargs = "server.js"\n'),
                ("malformed element",
                 '[mcp_servers.docx]\ncommand = "node"\nargs = ["a", bad bad]\n')):
            cfg.write_text(text, encoding="utf-8")
            check(f"F113 a {label} is UNREADABLE, not an empty argv",
                  pp.mcp_server_spec("docx") == {}, str(pp.mcp_server_spec("docx")))
        cfg.write_text('[mcp_servers.docx]\ncommand = "node"\n', encoding="utf-8")
        check("F113 an absent args key is still an empty argv",
              pp.mcp_server_spec("docx") == {"command": "node", "args": []})
    finally:
        pp.codex_config_path = real


# ---------------------------------------------------------------- F114
def test_f114_repair_writable_scope():
    for rel, kind in (("base/MANUAL_STEPS.md", "revise"),
                      ("non_revised/MANUAL_STEPS.md", "revise"),
                      ("others/w1/MANUAL_STEPS.md", "integrate")):
        check(f"F114 {rel} is NOT writable for a {kind} repair",
              not pp._repair_path_writable(Path(rel), kind)
              and not pp._repair_path_creatable(Path(rel), kind))
    for rel, kind in (("revised/MANUAL_STEPS.md", "revise"),
                      ("integrated/MANUAL_STEPS.md", "integrate"),
                      ("revised/work/notes.md", "revise")):
        check(f"F114 {rel} stays writable for a {kind} repair",
              pp._repair_path_writable(Path(rel), kind))


# ---------------------------------------------------------------- F115
def test_f115_foreign_stray_signal():
    class Ctx:
        def __init__(self, root):
            self.root = root
            self.state = {}

        def sandbox_of(self, rec):
            return self.root / rec["sandbox"]

    root = scratch("k115_") / "root"
    sb = root / "runs" / "r1_audit"
    (sb / "audit").mkdir(parents=True)
    pp.write_json_atomic(sb / "audit" / pp.MARKER_FILE,
                         {"stage": "guided_review", "run_id": "r1_guided_review",
                          "round": 1, "status": "complete"})
    ctx = Ctx(root)
    rec = {"id": "r1_audit", "kind": "audit", "round": 1, "sandbox": "runs/r1_audit"}
    check("F115 another stage's stray marker is NOT a completion signal",
          not pp.completion_signal_exists(ctx, rec))
    # ... while a stray marker that names THIS run (which relocation adopts) is one.
    pp.write_json_atomic(sb / "audit" / pp.MARKER_FILE,
                         {"stage": "audit", "run_id": "r1_audit", "round": 1,
                          "status": "complete"})
    check("F115 this run's own stray marker is still a completion signal",
          pp.completion_signal_exists(ctx, rec))
    check("F115 ... and relocation adopts it",
          len(pp.relocate_stray_signal(ctx, rec)) == 1
          and (sb / pp.MARKER_FILE).is_file())


# ---------------------------------------------------------------- F116
def test_f116_note_route_denial():
    check("F116 a note saying the prior proposal was NOT re-probed is refused",
          not pp.prior_proposal_dispositioned(
              "M37", "", "M37 is a prior proposal that was NOT re-probed anywhere"))
    check("F116 the documented 'no instances in base/' note still passes",
          pp.prior_proposal_dispositioned(
              "M38", "",
              "# D5\n\nNo new sweep proposals: prior proposal M38: no instances in base/."))
    check("F116 a real denial on the probe route is still refused",
          not pp.prior_proposal_dispositioned("M37", "we did not re-probe M37", ""))


# ---------------------------------------------------------------- F117
def test_f117_dropped_discovery_row():
    check("F117 the prompt's `dropped -- not in force` row reconciles the id",
          pp.discovery_ledger_missing(
              "| X-004 | donor | dropped -- not in force |", ["X-004"]) == [])
    check("F117 a ported row still reconciles", 
          pp.discovery_ledger_missing("| X-004 | ported |", ["X-004"]) == [])
    check("F117 a decisionless row is still not a reconciliation",
          pp.discovery_ledger_missing("| X-004 | donor | ??? |", ["X-004"]) == ["X-004"])


# ---------------------------------------------------------------- F118
def test_f118_added_raw_data_file_is_reported():
    pristine = scratch("k118p_")
    (pristine / "raw_data").mkdir(parents=True)
    (pristine / "raw_data" / "base.tsv").write_text("a\n", encoding="utf-8")
    root = scratch("k118r_")
    winner = root / "winners" / "w1"
    (winner / "raw_data").mkdir(parents=True)
    (winner / "raw_data" / "base.tsv").write_text("a\n", encoding="utf-8")
    (winner / "raw_data" / "sneaked-extra.tsv").write_text("x\n", encoding="utf-8")

    class Ctx:
        def __init__(self):
            self.root = root
            self.pristine = pristine
            self.state = {"pinned": [],
                          "rounds": {"1": {"status": "done", "winner_dir": "winners/w1"}}}

        def rounds_count(self):
            return 1

    notes = pp.raw_data_advisories(Ctx())
    check("F118 an ADDED raw-data file is reported by the advisory",
          len(notes) == 1 and "sneaked-extra.tsv" in notes[0], json.dumps(notes)[:240])


# ---------------------------------------------------------------- F119
def test_f119_empty_pristine_raw_data_is_enforced():
    pristine = scratch("k119p_")
    (pristine / "raw_data").mkdir(parents=True)            # exists but EMPTY
    cand = scratch("k119c_") / "revised"
    (cand / "raw_data").mkdir(parents=True)
    added = cand / "raw_data" / "agent-added.tsv"
    added.write_text("x\n", encoding="utf-8")

    class Ctx:
        def __init__(self):
            self.pristine = pristine

    warns = []
    info = pp.enforce_readonly_raw_data(Ctx(), cand, warns)
    check("F119 an empty pristine raw_data/ no longer exempts added files",
          info["dropped"] == ["raw_data/agent-added.tsv"] and not added.exists(),
          f"{info} {warns}")
    check("F119 the repair is still reported", bool(warns), str(warns)[:200])


# ---------------------------------------------------------------- F120
def test_f120_prior_audit_record_is_not_silently_empty():
    sb = scratch("k120_")
    (sb / "prior_audit").mkdir()
    (sb / "guided_review").mkdir()
    (sb / "prior_audit" / "UNRESOLVED.md").write_text(
        "| id | observation |\n|---|---|\n"
        "| AU-OBS-001 | base/a.docx:3 -- the quote does not appear |\n", encoding="utf-8")
    ids = pp.prior_audit_observation_ids(sb)
    check("F120 a TABLE-form record yields its observations",
          isinstance(ids, list) and len(ids) == 1 and ids[0][0] == "AU-OBS-001",
          str(ids)[:240])
    probs = pp.prior_audit_disposition_problems(sb, {"findings": []})
    check("F120 an undisposed table-form observation fails the gate",
          len(probs) == 1 and "AU-OBS-001" in probs[0], str(probs)[:240])
    # an over-budget record is UNKNOWN, not empty
    sb2 = scratch("k120b_")
    (sb2 / "prior_audit").mkdir()
    (sb2 / "guided_review").mkdir()
    (sb2 / "prior_audit" / "UNRESOLVED.md").write_text(
        "x" * (pp.MAX_JSON_BYTES + 100) + "\n", encoding="utf-8")
    probs = pp.prior_audit_disposition_problems(sb2, {"findings": []})
    check("F120 an unreadable record is UNKNOWN, not a vacuous pass",
          len(probs) == 1 and "cannot be read" in probs[0], str(probs)[:240])


# ---------------------------------------------------------------- F122
def test_f122_checked_at_is_a_real_date():
    def problems_for(checked_at):
        pkg = scratch("k122_")
        (pkg / "work").mkdir()
        (pkg / "work" / "FACT_VERIFICATION.json").write_text(json.dumps({"rows": [{
            "kind": "doi", "after": "10.1000/abc123", "before": "",
            "source_url": "https://doi.org/10.1000/abc123", "query": "10.1000/abc123",
            "checked_at": checked_at,
            "evidence": "the DOI 10.1000/abc123 resolves to the cited article"}]}),
            encoding="utf-8")
        return pp._fact_verification_rows(pkg)[1]

    check("F122 an impossible date is rejected",
          any("real calendar date" in p for p in problems_for("2026-99-99")),
          str(problems_for("2026-99-99")))
    check("F122 a day out of range is rejected",
          any("real calendar date" in p for p in problems_for("2026-02-31")))
    check("F122 a real date still passes", problems_for("2026-02-28") == [],
          str(problems_for("2026-02-28")))


# ---------------------------------------------------------------- F123
def test_f123_scoped_review_may_really_dispose():
    sb = scratch("k123_")
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    checks = [f"M{i}" for i in range(1, 37)] + [f"J{i}" for i in range(1, 6)]

    def run(m2_disp):
        rows = [{"check": c, "disposition": "clean -- basis: artifacts/M1_acronyms.md"}
                for c in checks]
        rows[1] = {"check": "M2", "disposition": m2_disp}
        errs = []
        pp.check_review_contract(None, sb, {"submission_dir": "./base", "findings": [],
                                            "coverage": rows}, errs, [],
                                 scope="formatting-writing", split="off")
        return errs

    for real in ("2 findings", "clean -- basis: artifacts/M2_citations.md"):
        errs = run(real)
        check(f"F123 a real out-of-scope disposition ({real!r}) is accepted",
              not [e for e in errs if "'M2'" in e and "scoped OUT" in e],
              "\n".join(errs)[-300:])
    errs = run("cannot")
    check("F123 a silent/filler row for a scoped-out check still fails",
          any("'M2'" in e and "scoped OUT" in e for e in errs), "\n".join(errs)[-300:])


# ---------------------------------------------------------------- F124
def test_f124_cover_letter_row_must_name_the_proven_letter():
    sb = scratch("k124_")
    (sb / "base").mkdir()
    art = sb / "guided_review" / "artifacts"
    art.mkdir(parents=True)
    real_scan, real_policy = pp.scan_format_in_sources, pp.format_policy_of
    pp.scan_format_in_sources = lambda *a, **k: {
        "rows": [{"rule": "FMT-CL1", "document": "coverLetter.docx"}]}
    pp.format_policy_of = lambda ctx: {}
    try:
        (art / "M20_formatting.md").write_text(
            "| rule | evidence | disposition |\n|---|---|---|\n"
            "| FMT-CL1 | other_letter.docx is stamped | F-042: restyle other_letter.docx |\n",
            encoding="utf-8")
        check("F124 a row naming a DIFFERENT document does not dispose the proven letter",
              bool(pp.cover_letter_row_survival_problems(object(), sb)))
        (art / "M20_formatting.md").write_text(
            "| rule | evidence | disposition |\n|---|---|---|\n"
            "| FMT-CL1 | the letter is stamped | F-042: restyle the letter |\n",
            encoding="utf-8")
        check("F124 a row with no document token still clears the survival gate",
              not pp.cover_letter_row_survival_problems(object(), sb))
        (art / "M20_formatting.md").write_text(
            "| rule | evidence | disposition |\n|---|---|---|\n"
            "| FMT-CL1 | coverLetter.docx is stamped | F-042: restyle the letter |\n",
            encoding="utf-8")
        check("F124 the proven letter's own row clears the gate",
              not pp.cover_letter_row_survival_problems(object(), sb))
    finally:
        pp.scan_format_in_sources, pp.format_policy_of = real_scan, real_policy


for fn in (test_f111_seeded_m20_rows_cannot_be_deleted,
           test_f112_negated_count_disposition,
           test_f113_malformed_mcp_args,
           test_f114_repair_writable_scope,
           test_f115_foreign_stray_signal,
           test_f116_note_route_denial,
           test_f117_dropped_discovery_row,
           test_f118_added_raw_data_file_is_reported,
           test_f119_empty_pristine_raw_data_is_enforced,
           test_f120_prior_audit_record_is_not_silently_empty,
           test_f122_checked_at_is_a_real_date,
           test_f123_scoped_review_may_really_dispose,
           test_f124_cover_letter_row_must_name_the_proven_letter):
    fn()

for d in _TMP:
    shutil.rmtree(d, ignore_errors=True)

if FAILS:
    print(f"\n{len(FAILS)} CHECK(S) FAILED")
    sys.exit(1)
print("\nALL GROUP-K FIX-BUG CHECKS PASSED")

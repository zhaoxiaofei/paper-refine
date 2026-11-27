#!/usr/bin/env python3
"""Regression checks for the 2026-11-27 fix-bugs wave (run 20261127-084439).

Hermetic, stdlib-only where possible. Each check fails on the unpatched tree.
"""
from __future__ import annotations

import importlib.util
import json
import struct
import sys
import tempfile
import zlib
from pathlib import Path
from types import SimpleNamespace

WS = Path(__file__).resolve().parent.parent
FAILS = []


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("pp_fix_20261127", WS / "paper_pipeline.py")
fmt = load("fmt_fix_20261127", WS / "paper_docx_format.py")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def test_text_rules():
    print("\n== text rules ==")
    for text in ("See Image A. The left panel shows the signal.",
                 "We used Donor A. The next sample differed.",
                 "Samples came from Hospital A. The rest were controls."):
        check(f"F015 a capitalised label before a single letter ends the sentence: {text!r}",
              len(fmt.split_sentences(text)) == 2, str(fmt.split_sentences(text)))
    check("F015 a real middle initial still does not split",
          fmt.split_sentences("John F. Kennedy spoke.") == ["John F. Kennedy spoke."])
    check("F017 plural identifier cues mask the whole coordinate list",
          fmt.number_format_rows(["positions 1234 and 5678 were seen in 2,000 reads."]) == [])
    check("F017 a plain mixed convention is still reported",
          bool(fmt.number_format_rows(["1,000 samples and 2500 cells."])))
    check("F016 e.g., is an example marker, not the document",
          pp._json_from_text('{"a":1}\ne.g., {"b":2}', True) == {"a": 1})


def test_cli_and_json_guards():
    print("\n== CLI / defensive reads ==")
    parser = pp.build_parser()
    before = parser.parse_args(["--fail-tier", "warning", "status"]).fail_tier
    after = parser.parse_args(["status", "--fail-tier", "warning"]).fail_tier
    default = parser.parse_args(["status"]).fail_tier
    check("F090 --fail-tier before the command name is honoured", before == 2, before)
    check("F090 --fail-tier after the command name is honoured", after == 2, after)
    check("F090 the default is still CRITICAL (4)", default == 4, default)
    root = Path(tempfile.mkdtemp())
    (root / pp.LOCK_FILE).write_text("[1,2]", encoding="utf-8")
    try:
        holder = pp._root_lock_holder(root)
        check("F097 a JSON list lock file is treated as stale, not a crash", holder is None, holder)
    except AttributeError as exc:                              # noqa: BLE001
        check("F097 a JSON list lock file is treated as stale, not a crash", False, str(exc))


def test_image_gates():
    print("\n== visual evidence gates ==")
    d = Path(tempfile.mkdtemp())
    jpg = d / "stub.jpg"
    jpg.write_bytes(b"\xff\xd8\xff" + b"0" * 5)
    tif = d / "stub.tif"
    tif.write_bytes(b"II*\x00" + b"\x00" * 4)
    check("F031 an 8-byte JPEG magic stub is not a render", not pp._render_evidence_is_real(jpg))
    check("F031 an 8-byte TIFF header stub is not a render", not pp._render_evidence_is_real(tif))
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff"))
    iend = chunk(b"IEND", b"")
    bad = d / "bad.png"
    bad.write_bytes(sig + idat + ihdr + iend)
    good = d / "good.png"
    good.write_bytes(sig + ihdr + idat + iend)
    check("F032 a PNG whose IDAT precedes IHDR is refused",
          not pp._png_is_a_real_image(bad))
    check("F032 the correctly ordered PNG is still accepted",
          pp._png_is_a_real_image(good))


def test_gap_and_audit_rules():
    print("\n== discovery gap / audit evidence ==")
    root = Path(tempfile.mkdtemp())
    r2 = root / "guided_review" / "round2"
    r2.mkdir(parents=True)
    (r2 / "gap_table.md").write_text(
        "| class | status | check | evidence |\n|---|---|---|---|\n"
        "| x | UNCOVERED | M2 | checked by the sweep |\n", encoding="utf-8")
    check("F033 a placeholder class cell is not a named class",
          pp.discovery_gap_summary(root)["rows"] == 0)
    (r2 / "gap_table.md").write_text(
        "| class | status | check | evidence |\n|---|---|---|---|\n"
        "| citation drift | UNCOVERED | M2 | checked by the sweep |\n", encoding="utf-8")
    check("F033 a real class cell is still accepted",
          pp.discovery_gap_summary(root)["rows"] == 1)

    ids = ["F-001", "F-002", "F-003"]
    audit = {"dispositions": [
        {"id": fid, "verdict": "drop", "reason": "the quoted text is absent from the base file",
         "evidence": "F-001 F-002 F-003: the quoted text does not appear at the cited location"}
        for fid in ids], "adds": []}
    # Reorder the id list per row: still the same boilerplate.
    for row, order in zip(audit["dispositions"],
                          (("F-001", "F-002", "F-003"),
                           ("F-002", "F-003", "F-001"),
                           ("F-003", "F-001", "F-002"))):
        row["evidence"] = " ".join(order) + ": the quoted text does not appear at the cited location"
    probs = pp.audit_artifact_problems(audit, ids)
    check("F055 reordering the ids does not defeat the shared-evidence gate",
          any("SAME evidence" in p for p in probs), str(probs))


def test_repair_ledger_guards():
    print("\n== repair ledger guards ==")
    sb = Path(tempfile.mkdtemp())
    (sb / "concern_repair").mkdir()
    orig = [{"id": "R1-1", "source": "editor2.txt", "quote": "dose 2 mg",
             "summary": "dose", "author": "R", "action": "text", "disposition": "to-fix"}]
    new = [dict(orig[0], quote="dose two mg")]
    audit = {"rows": [{"id": "R1-1", "verdict": "defective",
                       "defects": [{"type": "wrong-quote", "wrong": "2", "correct": "two",
                                    "basis": "editor2.txt:1"}],
                       "reason": "quoted wrong", "evidence": "x"}]}
    row = {"id": "R1-1", "audit_verdict": "defective", "verdict": "confirmed",
           "action": "corrected", "reason": "fixed the quote here", "evidence": "editor2.txt:1"}
    ledger = {"rows": [row], "counts": {"input": 1, "kept": 0, "corrected": 1,
                                        "merged": 0, "dropped": 0, "rejected": 0}}
    path = sb / "concern_repair" / "REPAIR_LEDGER.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    check("F028 a correction passes although the wrong token occurs in another field",
          pp.concern_repair_ledger_problems(sb, audit, orig, new) == [],
          str(pp.concern_repair_ledger_problems(sb, audit, orig, new)))
    bad_counts = json.loads(json.dumps(ledger))
    bad_counts["counts"] = {"input": 999, "kept": 7, "corrected": -5,
                            "merged": "banana", "dropped": None, "rejected": 42}
    path.write_text(json.dumps(bad_counts), encoding="utf-8")
    check("F054 malformed counts are rejected",
          any("counts" in e for e in pp.concern_repair_ledger_problems(sb, audit, orig, new)))
    bad_av = json.loads(json.dumps(ledger))
    bad_av["rows"][0]["audit_verdict"] = "confirmed"
    path.write_text(json.dumps(bad_av), encoding="utf-8")
    check("F048 a false audit_verdict record is rejected",
          any("audit_verdict" in e for e in pp.concern_repair_ledger_problems(sb, audit, orig, new)))


def test_concern_source_blocks():
    print("\n== concern source fallback ==")
    r = 1

    class C:
        cfg = {"revision_mode": "major"}

        def run(self, rid):
            return {"status": "failed"} if rid == pp.rid_concern_repair(r) else {"status": "done"}

        def sandbox_of(self, rec):
            return Path("/tmp")

    check("F018 a failed mandatory concern repair blocks instead of falling back",
          pp._concern_source_rid(C(), r) == pp.rid_concern_repair(r))
    deps = pp.unmet_deps(C(), {"id": pp.rid_response_draft(r), "kind": "response_draft",
                               "round": r, "status": "pending"})
    check("F018 response_draft reports the failed repair as unmet",
          any(pp.rid_concern_repair(r) in str(d) for d in deps), str(deps))


def test_response_chain_rebinds():
    print("\n== response audit/repair chain ==")
    d = Path(tempfile.mkdtemp())
    (d / "response").mkdir()
    (d / "response" / "letter.md").write_text("new", encoding="utf-8")
    digest = pp.hash_manifest(d / "response")
    r = 1
    audit_rid, repair_rid = pp.rid_response_audit(r), pp.rid_response_repair(r)
    recs = {
        audit_rid: {"id": audit_rid, "kind": "response_audit", "round": r,
                    "status": "done", "sandbox": f"runs/{audit_rid}",
                    "response_corpus_digest": {"old": "digest"}},
        repair_rid: {"id": repair_rid, "kind": "response_repair", "round": r,
                     "status": "done", "sandbox": f"runs/{repair_rid}",
                     "response_corpus_digest": {"old": "digest"}},
    }

    class C:
        runs_dir = d / "runs"

        def run(self, rid):
            return recs.get(rid)

        def sandbox_of(self, rec):
            return d / rec["sandbox"]

        def save_state(self):
            pass

    ctx = C()
    waves = []

    def materialize(kind):
        def f(c, rr):
            rec = recs[audit_rid if kind == "response_audit" else repair_rid]
            sb = c.sandbox_of(rec)
            (sb / "response").mkdir(parents=True, exist_ok=True)
            (sb / "response" / "letter.md").write_text("new", encoding="utf-8")
            rec["response_corpus_digest"] = digest
        return f

    def fake_wave(c, ids, cmd, timeout, jobs):
        waves.append(list(ids))
        for rid in ids:
            c.run(rid)["status"] = "done"
        return {}

    old_deps = pp.unmet_deps
    old_wave = pp.execute_wave
    old_mat_a = pp.materialize_response_audit
    old_mat_r = pp.materialize_response_repair
    pp.unmet_deps = lambda c, rec: []
    pp.execute_wave = fake_wave
    pp.materialize_response_audit = materialize("response_audit")
    pp.materialize_response_repair = materialize("response_repair")
    ph = dict(cmd="x", timeout=1, jobs=1, retries=0, manual=False,
              nowait=False, poll=1)
    try:
        out, ok, paused = pp.run_response_deliverable_chain(ctx, r, d, ph)
        check("F085 changed bytes rebuild both done records from the current response",
              all((ctx.sandbox_of(recs[rid]) / "response" / "letter.md").is_file()
                  for rid in (audit_rid, repair_rid)), "sandbox missing")
        check("F085 changed bytes rebuild and the REAL run_phase executes the audit "
              "and repair", waves == [[audit_rid], [repair_rid]], str(waves))
        check("F085 the chain then reports success and returns the repaired sandbox",
              bool(ok) and not paused and out == ctx.sandbox_of(recs[repair_rid])
              and recs[audit_rid]["status"] == "done"
              and recs[repair_rid]["status"] == "done", (ok, paused, str(out)))
        waves.clear()
        pp.run_response_deliverable_chain(ctx, r, d, ph)
        check("F085 an unchanged response reuses the bound audit and repair",
              waves == [], str(waves))
    finally:
        pp.unmet_deps = old_deps
        pp.execute_wave = old_wave
        pp.materialize_response_audit = old_mat_a
        pp.materialize_response_repair = old_mat_r


def test_pooled_and_evidence_scans():
    print("\n== pooled tables / evidence areas ==")
    d = Path(tempfile.mkdtemp())
    (d / "x_units.tsv").write_text("method\tn_units\tmean\nA\tnot-a-number\t5.0\n",
                                   encoding="utf-8")
    (d / "x_mcb_pooled.tsv").write_text("method\tn_units\tmean\nA\t1\t5.0\n", encoding="utf-8")
    rows = pp.scan_pooled_table_mismatches(d)
    check("F030 a malformed n_units is recorded as a gap, not accepted",
          any(r.get("gap") for r in rows), str(rows))
    d2 = Path(tempfile.mkdtemp())
    (d2 / "x_units.tsv").write_text("method\tn_units\tmean\nA\t21\t5.0\nB\t9\tnot-a-number\n",
                                    encoding="utf-8")
    (d2 / "x_mcb_pooled.tsv").write_text(
        "method\tn_units\tmean\nA\t21\t5.0\nB\t2\t9.0\n", encoding="utf-8")
    rows2 = pp.scan_pooled_table_mismatches(d2)
    check("F034 a method dropped for a malformed value is named as a gap",
          any("B" in str(r.get("detail")) and r.get("gap") for r in rows2), str(rows2))

    outside = d / "outside"
    outside.mkdir()
    (outside / "decision.rtf").write_text(
        r"{\rtf1 Decision letter: previous submission 2024-12-01, BMC Biology.}",
        encoding="utf-8")
    root = d / "pkg"
    root.mkdir()
    (root / "cover_letter.tex").write_text("Dear editor, this is a new submission.",
                                           encoding="utf-8")
    (root / "human_review_feedback").symlink_to(outside, target_is_directory=True)
    rows3 = pp.scan_prior_submission_disclosure(root, submitted_docs=["cover_letter.tex"])
    check("F029 a symlinked evidence area is refused and recorded as a gap",
          any(r.get("gap") for r in rows3), str(rows3))


def test_counts_and_xmp():
    print("\n== counts / metadata ==")
    agg = {"issue_census": {"v1": {}, "v2": {"tiers": {t: {"own": 0, "peer": 0}
                                                       for t in pp.BASIS_TIERS}}}}
    check("F045 a present-but-empty census row is not a measured 0",
          pp.census_prefix_total(agg, {"tiebreak": {"cells_used": 1}}, "v1") is None)
    xmp = (b'<rdf:Description xmp:CreatorTool="Laptop" pdf:Producer="Word" '
           b'dc:title="Secret"/>')
    out = pp._blank_xmp_fields(xmp)
    check("F098 attribute-encoded XMP creator/producer/title are blanked",
          b"Laptop" not in out and b"Word" not in out and b"Secret" not in out, out)


def test_recovery_persist():
    print("\n== recovery persistence ==")
    root = Path(tempfile.mkdtemp())
    session = pp.PaperRecovery(root, fail_tier=4, command="run", persist=False)
    session.start()
    session.finalize("completed")
    check("F102 persist=False writes no RECOVERY.md into the root",
          not (root / "RECOVERY.md").exists())
    check("F102 persist=False creates no .recovery directory in the root",
          not (root / ".recovery").exists())


def test_static_contracts():
    print("\n== source-level contracts ==")
    p09 = (WS / "paper_pipeline_parts" / "p09_setup.py").read_text(encoding="utf-8")
    check("F027 add-venue audits the same staging root the publisher installs",
          "output_rel=_art_root" in p09)
    check("F024 a response-stage --only selection drives the finalization",
          "_only_final" in p09 and '"response_audit"' in p09)
    mjs = (WS / "scripts" / "install-codex-mcp.mjs").read_text(encoding="utf-8")
    check("F012 --merge frees the replaced row's id as well as its name",
          "usedIds.delete(id)" in mjs)
    p02 = (WS / "paper_pipeline_parts" / "p02_journal_modes.py").read_text(encoding="utf-8")
    check("F050 the LLM-feedback sentence is qualified by the mode's stream policy",
          "major/minor are HUMAN-ONLY" in p02)
    p12 = (WS / "paper_pipeline_parts" / "p12_conflicts_decide.py").read_text(encoding="utf-8")
    check("F035 PKG-14 reads the formats its feedback reader supports",
          '".markdown", ".rst", ".tex"' in p12)
    p24 = (WS / "paper_pipeline_parts" / "p24_deliverable_audits.py").read_text(encoding="utf-8")
    check("F087 the concern repair verifies its recorded source digests",
          "recorded source digests do not match" in p24)
    p23 = (WS / "paper_pipeline_parts" / "p23_postchecks_mcp.py").read_text(encoding="utf-8")
    check("F104 a broken stdin routes through failure() (stderr/exit code kept)",
          "closed its stdin" in p23)
    check("F082 skipped checks print [skip], never a passing [ok]",
          "def skip(" in (WS / ".paper_test" / "test_general_audit_fixes_2026_1002c.py").read_text(encoding="utf-8"))


def main() -> int:
    test_text_rules()
    test_cli_and_json_guards()
    test_image_gates()
    test_gap_and_audit_rules()
    test_repair_ledger_guards()
    test_concern_source_blocks()
    test_response_chain_rebinds()
    test_pooled_and_evidence_scans()
    test_counts_and_xmp()
    test_recovery_persist()
    test_static_contracts()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED: {', '.join(FAILS)}")
        return 1
    print("ALL 2026-11-27 FIX-BUGS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

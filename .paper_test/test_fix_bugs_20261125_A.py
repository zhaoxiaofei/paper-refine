#!/usr/bin/env python3
"""Fix-bugs wave 1, group A (run 20261125-023107) -- one check per candidate.

Every check is hermetic: temp dirs only, no network, no Word/Office. The fake
MCP "server" is a local python script spawned by the client itself (the stdio
protocol is the object under test).

Run:  python3 .paper_test/test_fix_bugs_20261125_A.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1125a_pp", "paper_pipeline.py")

FAILS: list[str] = []
TMPDIRS: list[Path] = []


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        for p in [tmp, *tmp.rglob("*")]:
            with contextlib.suppress(OSError):
                if p.is_symlink():
                    continue
                p.chmod(0o755 if p.is_dir() else 0o644)
        shutil.rmtree(tmp, ignore_errors=True)


class Ctx:
    """The minimal Ctx the exercised helpers read (`cfg` + `pristine`)."""

    cfg: dict = {}

    def __init__(self, pristine: Path = None):
        self.pristine = pristine or Path("/nonexistent-pristine")


# ---------------------------------------------------------------- F002
def test_f002_seed_mkdir_is_guarded():
    print("\n== F002: seeding creates its output dirs through the symlink guard ==")
    pp.format_policy_of = lambda ctx: {}
    pp.scan_format_in_sources = lambda sources, policy=None: {"rows": []}
    # (a) guided_review/ itself is a link: the work/ mkdir must not follow it.
    sb = scratch("f002a_").joinpath("sb")
    sb.mkdir(parents=True)
    outside = scratch("f002a_out_")
    (sb / "guided_review").symlink_to(outside, target_is_directory=True)
    raised = None
    try:
        pp._seed_review_format_artifact(Ctx(), sb)
    except BaseException as e:                                        # noqa: BLE001
        raised = type(e).__name__
    check("F002 a symlinked guided_review/ is refused before work/ is created",
          raised is not None and not (outside / "work").exists(),
          f"raised={raised}, outside/work exists={(outside / 'work').exists()}")
    # (b) guided_review/work is real but artifacts/ is a planted link.
    sb2 = scratch("f002b_").joinpath("sb")
    (sb2 / "guided_review" / "work").mkdir(parents=True)
    outside2 = scratch("f002b_out_")
    (sb2 / "guided_review" / "artifacts").symlink_to(outside2, target_is_directory=True)
    raised2 = None
    try:
        pp._seed_review_format_artifact(Ctx(), sb2)
    except BaseException as e:                                        # noqa: BLE001
        raised2 = type(e).__name__
    check("F002 a symlinked artifacts/ is refused before the seed is written",
          raised2 is not None and not (outside2 / "M20_formatting.md").exists(),
          f"raised={raised2}, seed written={(outside2 / 'M20_formatting.md').exists()}")
    # (c) the evidence-pack seeder (its own work/ mkdir, same mechanism).
    sb3 = scratch("f002c_").joinpath("sb")
    sb3.mkdir(parents=True)
    outside3 = scratch("f002c_out_")
    (sb3 / "guided_review").symlink_to(outside3, target_is_directory=True)
    raised3 = None
    try:
        pp.seed_evidence_pack(Ctx(), sb3, sb3 / "base", "review")
    except BaseException as e:                                        # noqa: BLE001
        raised3 = type(e).__name__
    check("F002 seed_evidence_pack refuses a symlinked guided_review/",
          raised3 is not None and not (outside3 / "work").exists(),
          f"raised={raised3}, outside/work exists={(outside3 / 'work').exists()}")


# ---------------------------------------------------------------- F008
M20_HEADER = ("| # | rule | tier | severity | location | evidence | fix kind | disposition |\n"
              "|---|---|---|---|---|---|---|---|\n")


def test_f008_failed_m20_scan_does_not_trust_sandbox_scan():
    print("\n== F008: a failed M20 re-derivation never falls back to the sandbox scan ==")
    sb = scratch("f008_").joinpath("sb")
    (sb / "base").mkdir(parents=True)
    (sb / "guided_review" / "work").mkdir(parents=True)
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    forged = {"rows": [{"rule": "FMT-T1", "severity": "minor", "location": "a.docx:1",
                        "evidence": "x", "fix": "style"} for _ in range(3)]}
    (sb / "guided_review" / "work" / "FORMAT_SCAN.json").write_text(
        json.dumps(forged), encoding="utf-8")
    (sb / "guided_review" / "artifacts" / "M20_formatting.md").write_text(
        M20_HEADER + "| 1 | FMT-T1 | finding | minor | a.docx:1 | x | style |"
        " OK — the sweep found nothing else |\n", encoding="utf-8")
    orig_scan = pp.scan_format_in_sources
    pp.scan_format_in_sources = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("scan exploded"))
    rec, errs, warns = {}, [], []
    try:
        pp.check_artifact_quality(Ctx(), rec, sb, errs, warns)
    finally:
        pp.scan_format_in_sources = orig_scan
    m20 = (rec.get("artifact_quality") or {}).get("artifacts/M20_formatting.md") or []
    check("F008 a failed code-side scan is recorded as UNKNOWN",
          any("M20 cannot be verified" in p for p in m20), str(m20)[:240])
    check("F008 the forged sandbox FORMAT_SCAN.json supplies no seeded-row count",
          not any("code-seeded row(s) are no longer in the table" in p for p in m20),
          str(m20)[:240])


# ---------------------------------------------------------------- F044 / F072
def _fake_server(script_text: str) -> dict:
    tmp = scratch("fakemcp_")
    script = tmp / "server.py"
    script.write_text(script_text, encoding="utf-8")
    return {"command": sys.executable, "args": [str(script)]}


F044_SERVER = r'''
import json, sys
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if msg.get("method") == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "result": {}}), flush=True)
    elif msg.get("method") == "tools/call":
        # A legal server->client REQUEST whose id collides with the call id.
        print(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "method": "ping"}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"),
                          "result": {"content": [{"type": "text",
                                                  "text": "REAL-RESULT-MARKER"}]}}), flush=True)
'''

F072_SERVER = r'''
import json, sys
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if msg.get("method") == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "result": {}}), flush=True)
    elif msg.get("method") == "tools/call":
        # A deeply nested LINE raises RecursionError in json.loads.
        deep = "[" * 200000 + "]" * 200000
        print('{"jsonrpc":"2.0","id":' + str(msg.get("id")) + ',"o":' + deep + '}', flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"),
                          "result": {"content": [{"type": "text",
                                                  "text": "REAL-RESULT-MARKER"}]}}), flush=True)
'''


def test_f044_response_shape_required():
    print("\n== F044: wait_for does not accept a server REQUEST as the tool response ==")
    spec = _fake_server(F044_SERVER)
    rep = pp.mcp_stdio_tool_call(spec, "render", {}, timeout=60)
    text = json.dumps(rep)
    check("F044 a colliding server request is not returned as the tools/call result",
          rep.get("ok") is True and "REAL-RESULT-MARKER" in text, text[:240])


def test_f072_recursion_error_is_contained():
    print("\n== F072: a deeply nested server line is unparsable, not a crash ==")
    spec = _fake_server(F072_SERVER)
    exc = None
    rep = None
    try:
        rep = pp.mcp_stdio_tool_call(spec, "render", {}, timeout=60)
    except BaseException as e:                                        # noqa: BLE001
        exc = f"{type(e).__name__}: {e}"
    check("F072 a RecursionError from json.loads does not escape the tool call",
          exc is None, str(exc)[:200])
    check("F072 the real response after the bad line is still returned",
          exc is None and rep.get("ok") is True
          and "REAL-RESULT-MARKER" in json.dumps(rep), str(rep)[:240])


# ---------------------------------------------------------------- F083
def test_f083_provenance_ledgers_are_decision_artifacts():
    print("\n== F083: the number/identifier/gene ledgers are gated decision tables ==")
    sb = scratch("f083_").joinpath("sb")
    (sb / "base").mkdir(parents=True)
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    (sb / "guided_review" / "artifacts" / "NUMBERS_LEDGER.md").write_text(
        "| # | document | paragraph | number | unit | sentence | source | source_kind |"
        " status | disposition |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        "| 1 | a.docx | 3 | 12 | % | twelve percent | recomputed: t.csv | shipped-table |"
        " proved |  |\n", encoding="utf-8")
    pins = pp.review_seeded_row_pins(Ctx(), sb / "base")
    for rel in ("artifacts/M4_numbers.md", "artifacts/NUMBERS_LEDGER.md",
                "artifacts/IDENTIFIERS.md", "artifacts/GENE_LEDGER.md"):
        check(f"F083 the seeded-row pin covers {rel}", rel in pins, str(sorted(pins))[:300])
    rec, errs, warns = {}, [], []
    pp.check_artifact_quality(Ctx(), rec, sb, errs, warns)
    nbl = (rec.get("artifact_quality") or {}).get("artifacts/NUMBERS_LEDGER.md") or []
    check("F083 an EMPTY disposition in NUMBERS_LEDGER.md is reported",
          any("EMPTY disposition cell" in p or "EMPTY" in p for p in nbl), str(nbl)[:240])
    check("F083 a deleted IDENTIFIERS.md/GENE_LEDGER.md is reported as missing",
          all(any(rel in p for p in (rec.get("artifact_quality") or {}).get(rel) or [])
              for rel in ("artifacts/IDENTIFIERS.md", "artifacts/GENE_LEDGER.md")),
          str({k: v for k, v in (rec.get("artifact_quality") or {}).items()
               if "IDENT" in k or "GENE" in k})[:300])
    # The orchestrator's OWN seed must not be reported as deleted/replaced: the
    # pins' identity columns must be the cells the seed actually renders.
    seeded = scratch("f083seed_") / "sb"
    (seeded / "base").mkdir(parents=True)
    (seeded / "base" / "manuscript.md").write_text(
        "Abstract\n\nWe analysed 12 samples; DOI 10.1234/abc.def.\n\n"
        "Methods\n\nThe parameter was 0.81.\n", encoding="utf-8")
    pp.seed_evidence_pack(SimpleNamespace(cfg={"placeholder_lookup": "off"}),
                          seeded, seeded / "base", "review")
    rec2 = {}
    pp.check_artifact_quality(SimpleNamespace(cfg={"placeholder_lookup": "off"}),
                              rec2, seeded, [], [])
    bad = {rel: [p for p in (rec2.get("artifact_quality") or {}).get(rel) or []
                 if "code-seeded row" in p or "is missing" in p
                 or "no decision table" in p]
           for rel in pp.PROVENANCE_DECISION_ARTIFACTS}
    check("F083 the orchestrator's own provenance seed is not reported deleted/replaced",
          not any(bad.values()), str(bad)[:400])


# ---------------------------------------------------------------- F084
def _png_bytes(sig_only: bool = False) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    if sig_only:
        return sig
    ihdr = (13).to_bytes(4, "big") + b"IHDR" + (800).to_bytes(4, "big") \
        + (600).to_bytes(4, "big") + bytes([8, 2, 0, 0, 0]) + b"\x00\x00\x00\x00"
    idat = (4).to_bytes(4, "big") + b"IDAT" + b"\x78\x9c\x01\x00" + b"\x00\x00\x00\x00"
    iend = (0).to_bytes(4, "big") + b"IEND" + b"\x00\x00\x00\x00"
    return sig + ihdr + idat + iend


def test_f084_visual_evidence_requires_a_body():
    print("\n== F084: a signature-only PDF/PNG is not proof of a rendered page ==")
    tmp = scratch("f084_")
    stub_pdf = tmp / "stub.pdf"
    stub_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    check("F084 the 15-byte empty PDF stub is not a render",
          pp._render_evidence_is_real(stub_pdf) is False)
    sig_png = tmp / "sig.png"
    sig_png.write_bytes(_png_bytes(sig_only=True))
    check("F084 the 8-byte PNG signature is not a render",
          pp._render_evidence_is_real(sig_png) is False)
    real_pdf = tmp / "real.pdf"
    real_pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Page >>\nendobj\n"
                         b"trailer\n<< >>\n%%EOF\n")
    check("F084 a PDF with a real body is still accepted",
          pp._render_evidence_is_real(real_pdf) is True)
    real_png = tmp / "real.png"
    real_png.write_bytes(_png_bytes())
    check("F084 a PNG with an IHDR and image data is still accepted",
          pp._render_evidence_is_real(real_png) is True)


# ---------------------------------------------------------------- F085
def test_f085_judge_free_form_fmt_cl1():
    print("\n== F085: the judge's free-form FMT-CL1 line gets the OK/journal test ==")
    for line, why in (
            ("- FMT-CL1 | OK -- the run carries the letter in the journal styles",
             "rule-id-first OK closure"),
            ("FMT-CL1: not reviewed, no consideration recorded",
             "bare non-disposition mention")):
        sb = scratch("f085_")
        art = sb / "judge_review" / "artifacts"
        art.mkdir(parents=True)
        (art / "M20_formatting.md").write_text(
            "# M20\n\n" + line + "\n", encoding="utf-8")
        problems = pp.judge_cover_letter_artifact_problems(
            sb, [{"document": "cover_letter.docx", "rule": "FMT-CL1"}])
        check(f"F085 {why} is reported", bool(problems), str(problems)[:240])


# ---------------------------------------------------------------- F086
def test_f086_discovery_decision_cell():
    print("\n== F086: a decision word in an evidence cell is not a disposition ==")
    empty_decision = "| X-001 | the donor DROPPED this row | |\n"
    missing = pp.discovery_ledger_missing(empty_decision, ["X-001"])
    check("F086 a row whose decision cell is EMPTY is not reconciled",
          missing == ["X-001"], str(missing))
    escaped = "| X-001 | the donor DROPPED this row \\| per note | |\n"
    missing2 = pp.discovery_ledger_missing(escaped, ["X-001"])
    check("F086 an escaped pipe does not credit the evidence cell as the decision",
          missing2 == ["X-001"], str(missing2))
    good = "| X-001 | PORTED -- merged into base/main.md |\n"
    check("F086 a real decision cell is still reconciled",
          pp.discovery_ledger_missing(good, ["X-001"]) == [], str(good))


# ---------------------------------------------------------------- F087
def test_f087_pending_far_from_the_id():
    print("\n== F087: a `pending` status anywhere in the probe row is decisive ==")
    row = "| M37 | " + "x" * 120 + " | pending |\n"
    check("F087 a long row still marked pending is not a re-probe",
          pp.prior_proposal_dispositioned("M37", row, "") is False, row[:80])
    good = "| M37 | " + "x" * 120 + " | clean -- no instances |\n"
    check("F087 a long row with a real probe result is still accepted",
          pp.prior_proposal_dispositioned("M37", good, "") is True, good[:80])
    check("F087 a denial far from the id is still refused",
          pp.prior_proposal_dispositioned(
              "M37", "| M37 | " + "x" * 120 + " | we did not re-probe it |\n", "") is False)


# ---------------------------------------------------------------- F088
def test_f088_empty_fabricated_feedback_dir():
    print("\n== F088: a fabricated EMPTY feedback dir is reported and fails ==")
    root = scratch("f088_")
    pristine = root / "pristine"
    pristine.mkdir()
    cand = root / "revised"
    (cand / pp.HUMAN_FEEDBACK_DIR).mkdir(parents=True)
    warns = []
    info = pp.enforce_readonly_feedback_area(
        SimpleNamespace(pristine=pristine), cand, warns, pp.HUMAN_FEEDBACK_DIR)
    check("F088 the fabricated empty area is removed",
          not (cand / pp.HUMAN_FEEDBACK_DIR).exists(), str(info)[:200])
    check("F088 the fabricated empty area is WARNED and FAILED",
          bool(warns) and bool(info.get("failures")), str(info)[:240])


# ---------------------------------------------------------------- F089
def test_f089_adopted_sweep_finding_check_id():
    print("\n== F089: a finding filed under an adopted M37+ sweep passes the contract ==")
    sb = scratch("f089_")
    fj = {"findings": [{"id": "F-1", "location": "main.md:3", "check": "M37",
                        "evidence": "quote", "explanation": "why", "severity": "Major",
                        "category": 1, "status": "resolvable"}]}
    errs, warns = [], []
    pp.check_review_contract(None, sb, fj, errs, warns, scope="full", split="off")
    bad = [e for e in errs if "not an M/J check id" in e or "malformed finding" in e]
    check("F089 an M37 finding is not reported as a malformed check id",
          not bad, str(bad)[:240])


# ---------------------------------------------------------------- F090
def test_f090_no_work_filler():
    print("\n== F090: no-work coverage bases and `OK - unchanged` are filler ==")
    check("F090 `clean -- basis: nothing to report` is refused",
          pp._coverage_disposition_ok("clean -- basis: nothing to report") is False)
    check("F090 `0 findings; nothing to report` is refused",
          pp._coverage_disposition_ok("0 findings; nothing to report") is False)
    check("F090 a real clean basis is still accepted",
          pp._coverage_disposition_ok(
              "clean -- basis: artifacts/M1_acronyms.md") is True)
    check("F090 `OK - unchanged` is a filler disposition",
          pp._disposition_filler_closure("OK — unchanged") is True)
    check("F090 `OK - the row is inside its bar` is still accepted",
          pp._disposition_filler_closure("OK — the row is inside its bar") is False)


# ---------------------------------------------------------------- F091
def test_f091_stray_score_token():
    print("\n== F091: stray-score adoption compares the sheet to the opaque token ==")
    rec = {"id": "r2_j1", "kind": "judge", "target_id": "v2",
           "judge_target_token": "tok-abc", "round": 2}
    check("F091 a modern token-bearing sheet names this run",
          pp._signal_names_this_run({"target_id": "tok-abc"}, rec, pp.SCORES_FILE) is True)
    check("F091 a raw-id sheet still names this run (validator warns, accepts)",
          pp._signal_names_this_run({"target_id": "v2"}, rec, pp.SCORES_FILE) is True)
    check("F091 a foreign target still does not name this run",
          pp._signal_names_this_run({"target_id": "v9"}, rec, pp.SCORES_FILE) is False)
    check("F091 an anonymous sheet is never adopted",
          pp._signal_names_this_run({}, rec, pp.SCORES_FILE) is False)


# ---------------------------------------------------------------- F080
def test_f080_m30_test_observes_the_contract():
    print("\n== F080: the M30 coverage test reads the returned check-id list ==")
    required = pp.required_review_check_ids()
    check("F080 required_review_check_ids() returns M30", "M30" in required, str(required)[:240])
    src = (WS / ".paper_test" / "test_agent_consistency_2026_0922.py").read_text(
        encoding="utf-8")
    check("F080 the consistency test CALLS required_review_check_ids() for M30",
          "required_review_check_ids()" in src)


def main() -> int:
    try:
        test_f002_seed_mkdir_is_guarded()
        test_f008_failed_m20_scan_does_not_trust_sandbox_scan()
        test_f044_response_shape_required()
        test_f072_recursion_error_is_contained()
        test_f083_provenance_ledgers_are_decision_artifacts()
        test_f084_visual_evidence_requires_a_body()
        test_f085_judge_free_form_fmt_cl1()
        test_f086_discovery_decision_cell()
        test_f087_pending_far_from_the_id()
        test_f088_empty_fabricated_feedback_dir()
        test_f089_adopted_sweep_finding_check_id()
        test_f090_no_work_filler()
        test_f091_stray_score_token()
        test_f080_m30_test_observes_the_contract()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Accepted-output fixtures explicitly mock the mandatory audit's verdict.

These materialization/blinding unit tests do not run a full authoring round.
Their separately executed deterministic auditor supplies the accepted artifact
fixture; production acceptance guards remain enabled in the tests.
"""
import sys
from pathlib import Path


def audit_fixture(pp, ctx, rec):
    if rec.get("kind") not in ("revise", "response"):
        return
    sb = ctx.sandbox_of(rec)
    output = pp.WRITE_ARTIFACTS.get(rec["kind"], pp.REVISED_DIR)
    if not (sb / output).is_dir():
        return
    stub = Path(__file__).with_name("stub_agent.py")
    pp.audit_write_output(sb, rec, [sys.executable, str(stub)], 30,
                          output_rel=output, verify_only=True)
    if rec["kind"] == "revise":
        rec["revision_audit"] = {"status": "done", "rows": 0, "fixture": True}
        rec["revision_chain"] = "complete"

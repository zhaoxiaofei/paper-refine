#!/usr/bin/env python3
"""Independent sessions, bounded edits, exact-byte gates and scoped revisions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

WS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("mandatory_write_pipeline", WS / "paper_pipeline.py")
pp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pp
spec.loader.exec_module(pp)


class WriteAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sb = Path(self.tmp.name) / "writer"
        self.sb.mkdir()
        (self.sb / "PROMPT.md").write_text("original author mandate")
        (self.sb / "source").mkdir()
        (self.sb / "source" / "evidence.txt").write_text("n = 20")
        self.rec = {"id": "author", "kind": "response", "prompt_sha256": "writer-hash"}
        self.calls = []
        self.plan = [{"id": "RP-1", "file": "letter.md", "location": "line 1",
                      "wrong": "n = 10", "correct": "n = 20", "basis": "source/evidence.txt",
                      "evidence": "source records n = 20", "edit": "replace the incorrect value"}]
        self.output = self.sb / "response"
        self.output.mkdir()
        (self.output / "letter.md").write_text("n = 10\nUnrelated sentence.\n")
        self.before = (self.output / "letter.md").read_bytes()

    def fake(self, sb, rec, cmd, timeout, *args):
        self.calls.append((sb, rec["kind"], list(cmd)))
        if rec["kind"] in ("write-audit", "write-verification"):
            rows = self.plan if self.with_repair and rec["kind"] == "write-audit" else []
            pp.write_json_atomic(sb / "AUDIT.json", {"rows": rows, "blocked": []})
        elif rec["kind"] == "write-repair":
            p = sb / "artifact" / "letter.md"
            p.write_text(p.read_text().replace("n = 10", "n = 20"))
            pp.write_json_atomic(sb / "LEDGER.json", {"rows": [
                {"id": "RP-1", "verdict": "confirmed", "reason": "reread source/evidence.txt",
                 "before": "n = 10", "after": "n = 20"}]})
        return {"rc": 0, "dur": 0, "error": None}

    def audit(self, repair=False, fake=None):
        self.with_repair = repair
        with patch.object(pp, "_execute_attempt_raw", side_effect=fake or self.fake):
            return pp.audit_write_output(self.sb, self.rec, ["stub"], 10)

    def test_empty_plan_is_audited_without_repair(self):
        result = self.audit()
        self.assertEqual(result["status"], "done")
        self.assertEqual([c[1] for c in self.calls], ["write-audit"])
        self.assertEqual((self.output / "letter.md").read_bytes(), self.before)
        self.assertEqual(self.rec["prompt_sha256"], "writer-hash")

    def test_one_bounded_repair_and_independent_verification(self):
        self.audit(repair=True)
        self.assertEqual([c[1] for c in self.calls],
                         ["write-audit", "write-repair", "write-verification"])
        self.assertEqual(len({c[0] for c in self.calls}), 3)
        self.assertNotIn(self.sb, [c[0] for c in self.calls])
        self.assertEqual((self.output / "letter.md").read_text(), "n = 20\nUnrelated sentence.\n")
        self.assertEqual(pp.write_quality_problem(self.sb, "response", self.rec), "")

    def test_changed_output_invalidates_acceptance(self):
        self.audit()
        (self.output / "letter.md").write_text("different output")
        self.assertIn("stale", pp.write_quality_problem(self.sb, "response", self.rec))

    def test_changed_mandate_or_evidence_invalidates_acceptance(self):
        for relative in ("PROMPT.md", "source/evidence.txt"):
            with self.subTest(relative=relative):
                self.audit()
                path = self.sb / relative
                path.write_text(path.read_text() + " changed")
                self.assertIn("stale", pp.write_quality_problem(self.sb, "response", self.rec))

    def test_all_other_authoring_roles_use_owned_artifacts(self):
        for kind, output in pp.WRITE_ARTIFACTS.items():
            with self.subTest(kind=kind):
                self.rec["kind"] = kind
                if output != "response":
                    (self.sb / output).mkdir(exist_ok=True)
                    (self.sb / output / "owned.txt").write_text("owned")
                self.audit()
                self.assertEqual(pp.write_quality_problem(self.sb, kind, self.rec), "")

    def test_auditor_may_not_edit_input_or_artifact(self):
        for where in ("inputs", "artifact"):
            def malicious(sb, rec, cmd, timeout, *args):
                result = self.fake(sb, rec, cmd, timeout, *args)
                next(p for p in (sb / where).rglob("*") if p.is_file()).write_text("tampered")
                return result
            with self.subTest(where=where), self.assertRaisesRegex(ValueError, "read-only"):
                self.audit(fake=malicious)
            self.assertEqual((self.output / "letter.md").read_bytes(), self.before)

    def test_missing_malformed_unsafe_or_duplicate_plans_fail(self):
        for payload in (None, {"rows": "not a list"}, {"rows": [{"id": "RP-1"}]},
                        {"rows": [dict(self.plan[0], file="../escape")]},
                        {"rows": self.plan * 2}, {"rows": [], "blocked": ["new experiment needed"]}):
            def broken(sb, rec, cmd, timeout, *args):
                self.calls.append((sb, rec["kind"], cmd))
                if payload is not None:
                    pp.write_json_atomic(sb / "AUDIT.json", payload)
                return {"rc": 0, "error": None}
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.audit(fake=broken)

    def test_unplanned_rejected_noop_and_missing_ledger_repairs_fail(self):
        for mode in ("unplanned", "rejected", "noop", "missing", "tamper-plan", "tamper-input"):
            def broken(sb, rec, cmd, timeout, *args):
                result = self.fake(sb, rec, cmd, timeout, *args)
                if rec["kind"] == "write-repair":
                    if mode == "unplanned":
                        p = sb / "artifact" / "letter.md"
                        p.write_text(p.read_text().replace("Unrelated sentence.", "Unauthorized change."))
                    elif mode == "rejected":
                        pp.write_json_atomic(sb / "LEDGER.json", {"rows": [
                            {"id": "RP-1", "verdict": "rejected", "reason": "cannot confirm"}]})
                    elif mode == "noop":
                        (sb / "artifact" / "letter.md").write_bytes(self.before)
                    elif mode == "missing":
                        (sb / "LEDGER.json").unlink()
                    elif mode == "tamper-plan":
                        (sb / "PLAN.json").write_text("{}")
                    else:
                        (sb / "inputs" / "PROMPT.md").write_text("different mandate")
                return result
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.audit(repair=True, fake=broken)
            self.assertEqual((self.output / "letter.md").read_bytes(), self.before)

    def test_residual_verification_blocks_publication_without_second_repair(self):
        def residual(sb, rec, cmd, timeout, *args):
            result = self.fake(sb, rec, cmd, timeout, *args)
            if rec["kind"] == "write-verification":
                pp.write_json_atomic(sb / "AUDIT.json", {"rows": self.plan, "blocked": []})
            return result
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.audit(repair=True, fake=residual)
        self.assertEqual(sum(c[1] == "write-repair" for c in self.calls), 1)
        self.assertEqual((self.output / "letter.md").read_bytes(), self.before)

    def test_audit_failure_cannot_be_masked_by_valid_output(self):
        def failing(sb, rec, cmd, timeout, *args):
            return {"rc": 1, "error": "auditor crashed"}
        with self.assertRaisesRegex(ValueError, "auditor crashed"):
            self.audit(fake=failing)
        self.assertNotEqual(pp.write_quality_problem(self.sb, "response", self.rec), "")

    def test_author_cannot_supply_its_own_acceptance_receipt(self):
        # A failed author may have left valid-looking artifacts, including an
        # invented RESULT.json. Automatic acceptance requires the independent
        # orchestrator-owned receipt in the run record too.
        pp.write_json_atomic(self.sb / "write_quality" / "RESULT.json", {
            "status": "done", "role": "response",
            "artifact_digest": pp._write_owned_digest(self.output)})
        self.assertNotEqual(pp.write_quality_problem(self.sb, "response", self.rec), "")

    def test_fresh_commands_do_not_resume_the_author(self):
        for source, expected in [(["codex", "exec", "resume", "author-id", "-"], ["codex", "exec", "-"]),
                                 (["claude", "--print", "--resume", "author-id"], ["claude", "--print"]),
                                 (["dsh", "--session-id", "author-id", "-"], ["dsh", "-"])]:
            self.assertEqual(pp._write_fresh_command(source), expected)

    def test_pure_insertion_and_deletion_repairs_are_supported(self):
        for wrong, correct in (("", "Added statement."), ("Unrelated sentence.", "")):
            with self.subTest(wrong=wrong):
                pre = self.sb / "pre"
                post = self.sb / "post"
                pre.mkdir(exist_ok=True)
                post.mkdir(exist_ok=True)
                before = "n = 10\nUnrelated sentence.\n"
                after = before + correct if not wrong else before.replace(wrong, correct)
                (pre / "letter.md").write_text(before)
                (post / "letter.md").write_text(after)
                plan = [dict(self.plan[0], wrong=wrong, correct=correct)]
                ledger = self.sb / "LEDGER.json"
                pp.write_json_atomic(ledger, {"rows": [{"id": "RP-1", "verdict": "confirmed",
                    "reason": "independently checked",
                    "before": "Unrelated sentence." if not wrong else "n = 10 Unrelated sentence.",
                    "after": "Unrelated sentence. Added statement." if not wrong else "n = 10"}]})
                pp._write_repair_check(pre, post, plan, ledger)

    def test_tracking_auxiliaries_do_not_invalidate_the_owned_artifact(self):
        self.audit()
        (self.output / "manuscript.tracking-original.docx").write_bytes(b"derived copy")
        self.assertEqual(pp.write_quality_problem(self.sb, "response", self.rec), "")

    def test_guideline_conform_preserves_source_content_and_evidence(self):
        source = self.sb / "source"
        (source / "manuscript.md").write_text("Original scientific claim.\n")
        (source / "raw_data").mkdir()
        (source / "raw_data" / "data.csv").write_text("n\n20\n")
        out = self.sb / "out"
        import shutil
        shutil.copytree(source, out)
        (out / "REPLACEMENT_LEDGER.md").write_text('```json\n{"exceptions": []}\n```')
        self.assertTrue(pp.guideline_conform_postcheck(self.sb, source)["ok"])
        (out / "manuscript.md").write_text("Invented scientific claim.\n")
        self.assertFalse(pp.guideline_conform_postcheck(self.sb, source)["ok"])
        (out / "manuscript.md").write_text("Original scientific claim.\n")
        (out / "raw_data" / "data.csv").write_text("n\n99\n")
        self.assertFalse(pp.guideline_conform_postcheck(self.sb, source)["ok"])

    def test_non_writer_and_three_exceptions_do_not_start_audit_chain(self):
        for kind in ("rewrite", "integrate", "bounded-repair", "write-repair", "guided_review", "judge"):
            rec = {"id": "exempt", "kind": kind}
            with patch.object(pp, "_execute_attempt_raw", return_value={"rc": 0, "error": None}) as raw:
                pp._execute_attempt_in(self.sb, rec, ["stub"], 10)
                self.assertEqual(raw.call_count, 1)
                self.assertNotIn("write_quality", rec)

    def test_optouts_and_legacy_skip_records_do_not_disable_revision_audits(self):
        with patch.dict(os.environ, {"PAPER_REVISION_AUDIT": "off"}):
            self.assertEqual(pp.revision_audit_of(type("Ctx", (), {"cfg": {"revision_audit": "off"}})()), "on")
        self.assertTrue(pp.revision_chain_pending({"kind": "revise", "status": "done",
                                                  "revision_audit": {"status": "skipped", "reason": "audit off"}}))


class ScopedWorkflowTests(unittest.TestCase):
    def test_pruning_preserves_audited_decision_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, root = Path(tmp) / "source", Path(tmp) / "root"
            source.mkdir()
            (source / "manuscript.md").write_text("Abstract\nAn unchanged scientific claim.\n")
            def cli(*args):
                result = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"),
                                         *map(str, args)], capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-1000:])
                return result
            cli("setup", "--source", source, "--root", root, "--venue", "generic",
                "--rounds", "1", "--rewrites", "0", "--integrators", "0", "--judges", "1")
            cli("run", "--root", root, "--agent-cmd",
                json.dumps([sys.executable, str(WS / ".paper_test" / "stub_agent.py")]), "--retries", "0")
            cli("prune", "--root", root, "--keep-latest", "0", "--yes")
            self.assertFalse((root / "runs" / "r1_a2_revise").exists())
            self.assertTrue((root / "reports" / "write_quality" / "r1_a2_revise.json").is_file())
            cli("decide", "--root", root)

    def test_init_and_transfer_conform_without_word_templates_before_round_one(self):
        for mode in ("init", "transfer"):
            for suffix in (".md", ".tex"):
                with self.subTest(mode=mode, suffix=suffix), tempfile.TemporaryDirectory() as tmp:
                    source, root = Path(tmp) / "source", Path(tmp) / "root"
                    (source / "human_review_feedback").mkdir(parents=True)
                    (source / ("manuscript" + suffix)).write_text("Original scientific claim.\n")
                    (source / "human_review_feedback" / "review.txt").write_text(
                        "Reviewer 1:\n1. Clarify the methods.\n")
                    command = [sys.executable, str(WS / "paper_pipeline.py")]
                    setup = subprocess.run(command + ["setup", "--source", str(source), "--root", str(root),
                        "--revision-mode", mode, "--venue", "generic", "--rounds", "1"],
                        capture_output=True, text=True, timeout=60)
                    self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
                    result = subprocess.run(command + ["run", "--root", str(root), "--only", "conform",
                        "--agent-cmd", json.dumps([sys.executable, str(WS / ".paper_test" / "stub_agent.py")])],
                        capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
                    state = json.loads((root / "state.json").read_text())
                    self.assertTrue(state["template_stage"]["ok"])
                    quality = json.loads((root / "template_rewrite" / "write_quality" / "RESULT.json").read_text())
                    self.assertEqual(quality["status"], "done")
                    self.assertEqual((root / "template_rewrite" / "out" / ("manuscript" + suffix)).read_text(),
                                     "Original scientific claim.\n")
                    self.assertNotIn("r1_guided_review", state["runs"])

    def make_root(self, tmp, mode="init", extra=()):
        source, root = Path(tmp) / "source", Path(tmp) / "root"
        for area in ("human_review_feedback", "llm_review_feedback"):
            (source / area).mkdir(parents=True, exist_ok=True)
            (source / area / "review.txt").write_text("Reviewer 1:\n1. Clarify the methods.\n")
        (source / "manuscript.md").write_text("Original scientific claim.\n")
        result = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
            "--source", str(source), "--root", str(root), "--revision-mode", mode,
            "--venue", "generic", "--rounds", "1", "--rewrites", "0", "--integrators", "0", *extra],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        ctx = pp.Ctx(root)
        ctx.load()
        return ctx

    def test_required_stages_in_all_seven_modes(self):
        for mode in pp.JOURNAL_MODES:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                ctx = self.make_root(tmp, mode)
                kinds = {entry["kind"] for entry in pp.round_run_plan(ctx, 1)}
                self.assertIn("revise", kinds)
                self.assertEqual("response" in kinds, mode in ("major", "minor"))
                self.assertEqual(pp.journal_needs_response(ctx), mode in ("major", "minor", "resubmit"))
                self.assertEqual("concerns" in kinds, mode in ("major", "minor"))
                self.assertEqual("guided_review" in kinds, mode not in ("major", "minor"))
                self.assertEqual("feedback" in kinds, mode in ("transfer", "resubmit", "llm"))

    def test_conform_and_its_auditor_use_selected_producer_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self.make_root(tmp)
            stub = [sys.executable, str(WS / ".paper_test" / "stub_agent.py")]
            args = pp.build_parser().parse_args(["run", "--root", str(ctx.root),
                    "--only", "conform", "--agent-harness", "gpt-codex", "--agent-model", "gpt-sol"])
            with patch.object(pp, "resolve_agent_model_cmd", return_value=stub), \
                 patch.object(pp, "resolve_agent_cmd", side_effect=AssertionError("legacy backend selected")):
                with self.assertRaises(SystemExit) as stopped:
                    pp._cmd_run_locked(ctx, args)
            self.assertEqual(stopped.exception.code, 3)
            self.assertTrue(ctx.state["template_stage"]["ok"])

    def test_changed_destination_blocks_conform_reuse_without_losing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self.make_root(tmp)
            stub = [sys.executable, str(WS / ".paper_test" / "stub_agent.py")]
            args = pp.build_parser().parse_args(["run", "--root", str(ctx.root), "--only", "conform",
                                                "--agent-cmd", json.dumps(stub)])
            with self.assertRaises(SystemExit) as stopped:
                pp._cmd_run_locked(ctx, args)
            self.assertEqual(stopped.exception.code, 3)
            output = ctx.root / "template_rewrite" / "out" / "manuscript.md"
            before = output.read_bytes()
            ctx.cfg["journal"] = "A different destination journal"
            with self.assertRaises(SystemExit) as stopped:
                pp._cmd_run_locked(ctx, args)
            self.assertEqual(stopped.exception.code, 1)
            self.assertEqual(output.read_bytes(), before)

    def test_review_only_needs_no_judge_or_panel_auditor_executables(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self.make_root(tmp, "continue")
            result = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "run",
                "--root", str(ctx.root), "--only", "review", "--agent-cmd",
                json.dumps([sys.executable, str(WS / ".paper_test" / "stub_agent.py")]),
                "--judge-agent-cmd", '["nonexistent-judge"]',
                "--conflict-agent-cmd", '["nonexistent-conflict-auditor"]',
                "--defect-audit-cmd", '["nonexistent-panel-auditor"]'],
                capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            state = json.loads((ctx.root / "state.json").read_text())
            self.assertEqual(state["runs"]["r1_guided_review"]["status"], "done")
            self.assertFalse(any(rec["kind"] == "judge" for rec in state["runs"].values()))

    def test_registered_early_stop_still_runs_journal_finalization(self):
        for mode in ("transfer", "resubmit"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                ctx = self.make_root(tmp, mode, ("--rounds", "2", "--stop-after-no-progress", "1"))
                result = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "run",
                    "--root", str(ctx.root), "--agent-cmd",
                    json.dumps([sys.executable, str(WS / ".paper_test" / "stub_agent.py")]),
                    "--judge-agent-cmd", json.dumps([sys.executable,
                        str(WS / ".paper_test" / "test_redesign_v3.py"), "--as-zero-judge"]),
                    "--retries", "0", "--no-track"], capture_output=True, text=True, timeout=120,
                    env=dict(os.environ, PAPER_STUB_RESPONSE_ADDRESSED="1"))
                self.assertEqual(result.returncode, 0, result.stdout[-6000:] + result.stderr[-2000:])
                state = json.loads((ctx.root / "state.json").read_text())
                self.assertEqual(state["stopped_early"]["after_round"], 1)
                self.assertTrue((ctx.root / "journal_submission").is_dir())
                if mode == "resubmit":
                    self.assertEqual(state["runs"]["r1_response"]["write_quality"]["status"], "done")
                self.assertNotIn("r2_response", state["runs"])

    def test_major_and_minor_revisers_and_responses_are_independently_audited(self):
        for mode in ("major", "minor"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "root"
                src = Path(tmp) / "source"
                (src / "human_review_feedback").mkdir(parents=True)
                (src / "manuscript.md").write_text("Abstract\nThe manuscript describes a study.\n")
                (src / "human_review_feedback" / "review.txt").write_text(
                    "Reviewer 1:\n1. Clarify the methods in the manuscript.\n")
                def cli(*args):
                    r = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *map(str, args)],
                                       capture_output=True, text=True, timeout=180)
                    self.assertEqual(r.returncode, 0, r.stdout[-5000:] + r.stderr[-3000:])
                    return r
                cli("setup", "--source", src, "--root", root, "--revision-mode", mode,
                    "--venue", "generic", "--rounds", "1", "--rewrites", "0", "--integrators", "0")
                cli("run", "--root", root, "--agent-cmd",
                    json.dumps([sys.executable, str(WS / ".paper_test" / "stub_agent.py")]), "--retries", "0",
                    "--champion-select", "judge", "--judge-agent-cmd", '["nonexistent-judge"]',
                    "--conflict-agent-cmd", '["nonexistent-conflict-auditor"]')
                state = json.loads((root / "state.json").read_text())
                for rid in ("r1_a2_revise", "r1_response"):
                    rec = state["runs"][rid]
                    self.assertEqual(rec["write_quality"]["status"], "done")
                    self.assertEqual(rec["status"], "done")
                self.assertEqual(state["runs"]["r1_a2_revise"]["revision_audit"]["status"], "done")
                self.assertTrue((root / "journal_submission").is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)

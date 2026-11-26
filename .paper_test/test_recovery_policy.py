#!/usr/bin/env python3
"""Recovery-policy tests for paper-refine.

Covers the shared five-tier severity taxonomy, the strict
``rank > --fail-tier`` policy, ``RECOVERY.md`` placement under the resolved
``--root``, history preservation across runs, faithful partial/blocked
reporting, and consistency with the ``generic-debug-pipeline`` checkout.

Run directly (``python3 .paper_test/test_recovery_policy.py``) or through
``run_all.py``; it prints one ``[ok ]``/``[FAIL]`` line per check.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIPELINE = REPO / "paper_pipeline.py"
sys.path.insert(0, str(REPO / "agent-common"))

from agent_common import recovery as shared  # noqa: E402

CHECKS = []


def check(name):
    def decorate(function):
        CHECKS.append((name, function))
        return function

    return decorate


def make_root(base):
    """A minimal existing root that ``set-journal`` accepts without running a stage."""
    root = Path(base) / "root"
    source = Path(base) / "src"
    root.mkdir(parents=True)
    source.mkdir(parents=True)
    (source / "manuscript.md").write_text("# Title\n\nText.\n", encoding="utf-8")
    (root / "pipeline_config.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "rounds": 1,
                "judges": [1],
                "venue": "nature-biotechnology",
            }
        ),
        encoding="utf-8",
    )
    (root / "state.json").write_text(
        json.dumps({"version": 3, "runs": {}, "rounds": {}, "pinned": [], "log": []}),
        encoding="utf-8",
    )
    return root


def run_pipeline(args, cwd, env):
    return subprocess.run(
        [sys.executable, str(PIPELINE), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def base_env(tmp):
    env = dict(os.environ)
    env["PAPER_RECOVERY_FALLBACK_DIR"] = str(Path(tmp) / "fallback")
    env.pop("XDG_CACHE_HOME", None)
    return env


@check("shared taxonomy is the ordered five-tier scale")
def test_taxonomy(_tmp, _env):
    assert [shared.TIER_DEBUG, shared.TIER_INFO, shared.TIER_WARNING,
            shared.TIER_ERROR, shared.TIER_CRITICAL] == [0, 1, 2, 3, 4]
    assert [shared.tier_name(rank) for rank in range(5)] == [
        "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    ]
    for name, rank in shared.TIER_RANKS.items():
        assert shared.parse_fail_tier(name) == rank
        assert shared.parse_fail_tier(name.lower()) == rank
        assert shared.parse_fail_tier(str(rank)) == rank


@check("invalid --fail-tier values are rejected without substitution")
def test_invalid_tier(tmp, env):
    for value in ("SEVERE", "warn", "5", "-1", ""):
        proc = run_pipeline(["set-journal", "--fail-tier", value], REPO, env)
        assert proc.returncode == 2, (value, proc.returncode)
        assert (
            "unknown severity tier" in proc.stderr
            or "requires a tier" in proc.stderr
            or "tier rank must be" in proc.stderr
        ), proc.stderr
    # Names and integer ranks are accepted (and validated before any work).
    root = make_root(tmp)
    for value in ("debug", "INFO", "Warning", "error", "critical", "0", "4"):
        proc = run_pipeline(
            ["set-journal", "--root", str(root), "--fail-tier", value,
             "Nature Biotechnology"], REPO, env,
        )
        assert proc.returncode == 0, (value, proc.stderr[-500:])


@check("help lists --fail-tier on the executable and every subcommand")
def test_help(_tmp, env):
    top = run_pipeline(["--help"], REPO, env)
    assert top.returncode == 0
    assert "--fail-tier" in top.stdout
    import re as _re

    match = _re.search(r"\{([^}]+)\}", top.stdout, _re.S)
    names = [item.strip() for item in match.group(1).split(",")] if match else []
    assert names, "could not read the subcommand list from --help"
    for command in names:
        proc = run_pipeline([command, "--help"], REPO, env)
        assert proc.returncode == 0, command
        assert "--fail-tier" in proc.stdout, command


@check("setup refuses a non-empty root without polluting it")
def test_setup_nonempty_root(tmp, env):
    root = Path(tmp) / "occupied"
    source = Path(tmp) / "source"
    root.mkdir()
    source.mkdir()
    (root / "keep.txt").write_text("untouched", encoding="utf-8")
    (source / "manuscript.md").write_text("# T\n\nText.\n", encoding="utf-8")
    proc = run_pipeline(
        ["setup", "--source", str(source), "--root", str(root), "--rounds", "1",
         "--judges", "1", "--rewrites", "1", "--revises", "0", "--integrators", "0",
         "--venue", "generic"],
        REPO, env,
    )
    assert proc.returncode != 0
    assert (root / "keep.txt").read_text(encoding="utf-8") == "untouched"
    assert not (root / "RECOVERY.md").exists(), "failed setup must not write into the refused root"
    assert not (root / ".recovery").exists()


@check("a clean run writes RECOVERY.md under the resolved --root and states no recovery")
def test_placement_and_no_recovery(tmp, env):
    root = make_root(tmp)
    proc = run_pipeline(
        ["set-journal", "--root", str(root), "Nature Biotechnology"], REPO, env
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    report = root / "RECOVERY.md"
    assert report.is_file(), "RECOVERY.md must be directly in the output root"
    text = report.read_text(encoding="utf-8")
    assert "No recovery events were recorded" in text
    assert "completed" in text
    assert f"[recovery] report: {report}" in proc.stdout


@check("RECOVERY.md resolves a relative --root exactly as the command does")
def test_relative_root(tmp, env):
    root = make_root(tmp)
    proc = run_pipeline(
        ["set-journal", "--root", "./root", "Nature Biotechnology"], tmp, env
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    assert (root / "RECOVERY.md").is_file()
    assert not (tmp / "RECOVERY.md").exists()


@check("history is preserved across runs and each run is delimited")
def test_history(tmp, env):
    root = make_root(tmp)
    first = run_pipeline(
        ["set-journal", "--root", str(root), "Nature Biotechnology"], REPO, env
    )
    second = run_pipeline(["set-journal", "--root", str(root)], REPO, env)
    assert first.returncode == 0
    assert second.returncode != 0
    text = (root / "RECOVERY.md").read_text(encoding="utf-8")
    sections = re.findall(r"<!-- recovery-run:([^ ]+) -->", text)
    assert len(sections) == 2, sections
    assert text.count("Status: **completed**") >= 1
    assert "Status: **blocked**" in text
    assert "COMMAND_REFUSED" in text or "SAFETY_GUARD_TRIPPED" in text


@check("a refusal is recorded with its consequence and review need")
def test_refusal_record(tmp, env):
    root = make_root(tmp)
    proc = run_pipeline(["set-journal", "--root", str(root)], REPO, env)
    assert proc.returncode == 2
    text = (root / "RECOVERY.md").read_text(encoding="utf-8")
    assert "set-journal needs a journal name" in text
    assert "Human review: required" in text
    assert "Effect on outputs:" in text
    assert "Validation performed:" in text


@check("--fail-tier WARNING stops an ERROR diagnostic with the contract message")
def test_threshold_stop(tmp, env):
    root = make_root(tmp)
    proc = run_pipeline(
        ["set-journal", "--root", str(root), "--fail-tier", "WARNING"], REPO, env
    )
    assert proc.returncode == shared.THRESHOLD_EXIT_CODE, proc.returncode
    for expected in ("TIER-ERROR-COMMAND_REFUSED", "severity ERROR",
                     "configured --fail-tier WARNING", "affected operation"):
        assert expected in proc.stderr, expected
    text = (root / "RECOVERY.md").read_text(encoding="utf-8")
    assert "terminated" in text


@check("--fail-tier CRITICAL (the default) continues through a CRITICAL diagnostic")
def test_always_continue(tmp, env):
    root = make_root(tmp)
    proc = run_pipeline(
        ["set-journal", "--root", str(root), "--fail-tier", "CRITICAL"], REPO, env
    )
    assert proc.returncode == 2
    assert "deliberately stops the run" not in proc.stderr
    text = (root / "RECOVERY.md").read_text(encoding="utf-8")
    assert "terminated" not in text
    assert "blocked" in text


@check("a missing root is never created and the fallback report is reported")
def test_missing_root(tmp, env):
    missing = Path(tmp) / "does-not-exist"
    proc = run_pipeline(["run", "--root", str(missing)], REPO, env)
    assert proc.returncode != 0
    assert not missing.exists(), "recovery must not create a mistyped --root"
    reports = list((Path(tmp) / "fallback").rglob("RECOVERY.md"))
    assert len(reports) == 1, reports
    assert f"[recovery] report: {reports[0]}" in proc.stdout


@check("--skip-hash is recorded as a skipped check, not as verified work")
def test_skipped_checks(tmp, env):
    root = make_root(tmp)
    proc = run_pipeline(
        ["set-journal", "--root", str(root), "--skip-hash", "Nature Biotechnology"],
        REPO, env,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    text = (root / "RECOVERY.md").read_text(encoding="utf-8")
    assert "CHECKS_SKIPPED" in text
    assert "not verified by this run" in text
    assert "reported-only" in text


@check("strict threshold comparison treats equality as recover-and-continue")
def test_equality(_tmp, _env):
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory() as directory:
        journal = shared.RecoveryJournal(Path(directory) / "j", "r")
        journal.start()
        controller = shared.RecoveryController(
            run_id="r", policy=shared.FailurePolicy(shared.TIER_ERROR),
            journal=journal, logger=lambda line: None,
        )
        controller.error("SOME_CODE", "op", "message", recovery_action="recover")
        assert len(controller.records) == 1
        with_directory = shared.FailurePolicy(shared.TIER_WARNING)
        diag = shared.Diagnostic(shared.TIER_ERROR, "SOME_CODE", "op", "message")
        assert with_directory.exceeds(diag)
        assert not shared.FailurePolicy(shared.TIER_CRITICAL).exceeds(
            shared.Diagnostic(shared.TIER_CRITICAL, "X", "op", "m")
        )


def _load_recovery_part():
    import importlib.util

    path = REPO / "paper_pipeline_parts" / "p26_recovery.py"
    spec = importlib.util.spec_from_file_location("p26_recovery_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@check("every tier recovers by default and the report names each event")
def test_engine_every_tier(tmp, env):
    part = _load_recovery_part()
    root = make_root(tmp)
    session = part.PaperRecovery(root, fail_tier=shared.TIER_CRITICAL, command="run")
    session.start()
    session.controller.info("RUN_NOTE", "run", "note", recovery_action="continue")
    session.controller.warn("RETRY_ATTEMPT", "run", "retry", recovery_action="retry")
    session.controller.error("RETRY_EXHAUSTED", "stage", "failed", recovery_action="preserve")
    session.controller.critical("UNEXPECTED_EXCEPTION", "stage", "boom",
                                recovery_action="preserve and pause")
    paths = session.finalize("completed", exit_code=0)
    text = Path(paths[0]).read_text(encoding="utf-8")
    for code in ("TIER-INFO-RUN_NOTE", "TIER-WARNING-RETRY_ATTEMPT",
                 "TIER-ERROR-RETRY_EXHAUSTED", "TIER-CRITICAL-UNEXPECTED_EXCEPTION"):
        assert code in text, code
    assert "No recovery events were recorded" not in text


@check("the engine's threshold stops above the tier, records, and is equality-safe")
def test_engine_threshold(tmp, env):
    part = _load_recovery_part()
    root = make_root(tmp)
    session = part.PaperRecovery(root, fail_tier=shared.TIER_WARNING, command="run")
    session.start()
    try:
        session.controller.error("RETRY_EXHAUSTED", "stage", "failed",
                                 recovery_action="preserve")
    except shared.ThresholdExceeded as exc:
        assert exc.exit_code == shared.THRESHOLD_EXIT_CODE
    else:
        raise AssertionError("an ERROR must exceed --fail-tier WARNING")
    paths = session.finalize("terminated", exit_code=shared.THRESHOLD_EXIT_CODE)
    text = Path(paths[0]).read_text(encoding="utf-8")
    assert "TERMINATED" in text.upper()
    assert "TIER-ERROR-RETRY_EXHAUSTED" in text

    equal = part.PaperRecovery(make_root(Path(tmp) / "equal"), fail_tier=shared.TIER_ERROR,
                               command="run")
    equal.start()
    equal.controller.error("RETRY_EXHAUSTED", "stage", "failed", recovery_action="preserve")
    equal_paths = equal.finalize("completed")
    assert "TIER-ERROR-RETRY_EXHAUSTED" in Path(equal_paths[0]).read_text(encoding="utf-8")


@check("an unreadable root report falls back and the fallback is reported")
def test_engine_report_fallback(tmp, env):
    part = _load_recovery_part()
    root = make_root(tmp)
    (root / "RECOVERY.md").mkdir()  # makes the primary report unwritable
    session = part.PaperRecovery(root, fail_tier=shared.TIER_CRITICAL, command="run")
    session.start()
    session.controller.error("OUTPUT_WRITE_FAILED", "report", "cannot write",
                             recovery_action="write to the documented fallback")
    paths = session.finalize("blocked", exit_code=1)
    written = Path(paths[0])
    assert written.is_file(), written
    assert written != root / "RECOVERY.md"
    assert "TIER-ERROR-OUTPUT_WRITE_FAILED" in written.read_text(encoding="utf-8")


@check("an interrupted run is marked INTERRUPTED when the next run starts")
def test_engine_interrupted(tmp, env):
    part = _load_recovery_part()
    root = make_root(tmp)
    first = part.PaperRecovery(root, fail_tier=shared.TIER_CRITICAL, command="run")
    first.start()
    first.controller.warn("RETRY_ATTEMPT", "stage", "retrying", recovery_action="retry")
    # No finalize: simulate a process that died mid-run.
    second = part.PaperRecovery(root, fail_tier=shared.TIER_CRITICAL, command="run")
    second.start()
    second.finalize("completed", exit_code=0)
    text = (root / "RECOVERY.md").read_text(encoding="utf-8")
    assert "INTERRUPTED" in text
    assert text.count("<!-- recovery-run:") == 2


@check("bounded retries report exhaustion and fallback as degraded, not success")
def test_engine_retry_exhaustion(tmp, env):
    part = _load_recovery_part()
    root = make_root(tmp)
    session = part.PaperRecovery(root, fail_tier=shared.TIER_CRITICAL, command="run")
    session.start()
    result = session.controller.run_with_recovery(
        shared.Diagnostic(shared.TIER_ERROR, "RETRY_EXHAUSTED", "judge", "the panel failed"),
        "re-run the panel",
        lambda attempt: (_ for _ in ()).throw(RuntimeError("still failing")),
        max_attempts=2,
        fallback=lambda exc: "partial panel",
        fallback_description="use the partial panel",
        omissions=["the panel is incomplete"],
    )
    assert result.ok and result.degraded
    paths = session.finalize("completed", exit_code=0)
    text = Path(paths[0]).read_text(encoding="utf-8")
    assert "exhausted" in text
    assert "the panel is incomplete" in text


@check("an incomplete round is recorded with omissions and a resume recovery")
def test_incomplete_round_record(tmp, env):
    import types

    part = _load_recovery_part()
    root = make_root(tmp)
    session = part.PaperRecovery(root, fail_tier=shared.TIER_CRITICAL, command="run")
    session.start()
    part._RECOVERY_SESSION = session
    ctx = types.SimpleNamespace(root=root)
    part.record_incomplete_round(ctx, [1], detail="round 1 did not finish")
    paths = session.finalize("failed", exit_code=3)
    part._RECOVERY_SESSION = None
    text = Path(paths[0]).read_text(encoding="utf-8")
    assert "TIER-ERROR-RETRY_EXHAUSTED" in text
    assert "round(s) 1 did not complete" in text
    assert "explicit resume" in text

    tolerated_root = make_root(Path(tmp) / "tolerated")
    tolerated = part.PaperRecovery(
        tolerated_root, fail_tier=shared.TIER_CRITICAL, command="run"
    )
    tolerated.start()
    part._RECOVERY_SESSION = tolerated
    part.record_incomplete_round(
        types.SimpleNamespace(root=tolerated_root), [1], tolerated=True,
        detail="a best failed trial was used",
    )
    tolerated_paths = tolerated.finalize("partial", exit_code=0)
    part._RECOVERY_SESSION = None
    tolerated_text = Path(tolerated_paths[0]).read_text(encoding="utf-8")
    assert "TIER-WARNING-PARTIAL_RESULT" in tolerated_text
    assert "PROVISIONAL and uncertified" in tolerated_text


@check("the shared engine is byte-identical in both repositories")
def test_cross_repo(_tmp, _env):
    gdp = REPO.parent / "generic-debug-pipeline" / "agent-common" / "agent_common" / "recovery.py"
    if not gdp.is_file():
        raise unittest_skip("generic-debug-pipeline checkout is not available")
    assert gdp.read_bytes() == (REPO / "agent-common" / "agent_common" / "recovery.py").read_bytes()
    gdp_part = REPO.parent / "generic-debug-pipeline" / "gdp" / "recovery.py"
    if gdp_part.is_file():
        assert "agent_common" in gdp_part.read_text(encoding="utf-8")


class unittest_skip(Exception):
    pass


def main():
    failures = 0
    for name, function in CHECKS:
        tmp = tempfile.mkdtemp(prefix="paper-recovery-test-")
        env = base_env(tmp)
        try:
            function(Path(tmp), env)
        except unittest_skip as exc:
            print("[skip] %s (%s)" % (name, exc))
        except Exception as exc:  # noqa: BLE001 - the harness reports every check
            import traceback

            traceback.print_exc()
            print("[FAIL] %s: %s" % (name, exc))
            failures += 1
        else:
            print("[ok ] %s" % name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print("FAIL %d/%d recovery-policy checks failed" % (failures, len(CHECKS)))
        return 1
    print("OK %d recovery-policy checks passed" % len(CHECKS))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Champion selection without a judge panel (`--champion-select`).

Run:  python3 .paper_test/test_champion_select_2026_1025.py

Covers the operator override added on 2026-10-25: `judge` (default) keeps the
relative-judgment panel, `revise` promotes the round's single review-audit-
revised candidate (a2), and `integrate` promotes that candidate's integration
arm i<M+2>. The no-judge modes are an explicit operator choice, so the decision
is PROVISIONAL / NOT JUDGED, never certified -- and the content-addressed
pin/winner chain still works exactly like a panel-decided round.
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
HERE = Path(__file__).resolve().parent
STUB = HERE / "stub_agent.py"
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("csel_pipeline", WS / "paper_pipeline.py")
CLI = [sys.executable, str(WS / "paper_pipeline.py")]


def run(args, **kw):
    return subprocess.run(CLI + args, capture_output=True, text=True, timeout=1200, **kw)


def make_source(tmp: Path) -> Path:
    src = tmp / "source"
    src.mkdir(parents=True)
    (src / "manuscript-o.md").write_text(
        "# Title\n\nA stub manuscript for the champion-selection test.\n", encoding="utf-8")
    return src


def setup_root(tmp: Path, mode: str, *, revises: int = 1, integrators: int = 1,
               extra=()) -> Path:
    root = tmp / "root"
    r = run(["setup", "--source", str(make_source(tmp)), "--root", str(root),
             "--rounds", "1", "--judges", "1", "--rewrites", "0",
             "--revises", str(revises), "--integrators", str(integrators),
             "--champion-select", mode, *extra])
    check(f"setup --champion-select {mode} succeeds", r.returncode == 0,
          (r.stderr or r.stdout)[-300:])
    return root


def run_round(root: Path, extra=()):
    return run(["run", "--root", str(root), "--agent-cmd",
                json.dumps([sys.executable, str(STUB)]), "--retries", "0", *extra])


def test_helpers():
    print("\n== helpers and defaults ==")
    check("the default mode is judge", pp.DEFAULT_CHAMPION_SELECT == "judge")
    check("the accepted modes are judge/revise/integrate",
          pp.CHAMPION_SELECT_MODES == ("judge", "revise", "integrate"))
    ctx = type("C", (), {"cfg": {}})()
    check("an unset config means judge", pp.champion_select_of(ctx) == "judge")
    ctx = type("C", (), {"cfg": {"champion_select": "revise"}})()
    check("the config selects the mode", pp.champion_select_of(ctx) == "revise")
    ctx._champion_select_override = "judge"
    check("an invocation override wins over the config",
          pp.champion_select_of(ctx) == "judge")
    ctx._champion_select_override = "bogus"
    try:
        pp.champion_select_of(ctx)
        rejected = False
    except SystemExit as e:
        rejected = e.code not in (None, 0)
    check("an unknown override is a hard error, never a silent fallback", rejected)
    bad_cfg = type("C", (), {"cfg": {"champion_select": "revize"}})()
    try:
        pp.champion_select_of(bad_cfg)
        rejected = False
    except SystemExit as e:
        rejected = e.code not in (None, 0)
    check("an unknown persisted champion_select is a hard error", rejected)


def test_revise_mode():
    print("\n== revise mode: a2 is promoted, no judge run exists ==")
    tmp = scratch("csel_revise_")
    root = setup_root(tmp, "revise")
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("setup persists champion_select", cfg.get("champion_select") == "revise")
    r_part = run_round(root, ["--only", "review"])
    out_part = r_part.stdout + r_part.stderr
    check("a session-only --only selection never pins the auto-promoted version",
          r_part.returncode != 0 and "does not ask for the round DECISION" in out_part
          and not (root / "pinned" / "r1_a2").exists()
          and not (root / "round1_winner").exists(), out_part[-500:])
    r = run_round(root)
    check("the round completes", r.returncode == 0, (r.stdout or r.stderr)[-500:])
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    kinds = {rec.get("kind") for rec in (state.get("runs") or {}).values()}
    check("NO judge session ran", "judge" not in kinds, str(sorted(kinds)))
    rrec = (state.get("rounds") or {}).get("1") or (state.get("rounds") or {}).get(1) or {}
    check("the record marks the round auto-promoted and unjudged",
          rrec.get("auto_promoted") is True and rrec.get("judged") is False)
    check("the record names the mode in its frozen plan",
          (rrec.get("plan") or {}).get("champion_select") == "revise")
    check("the promoted version is a2", rrec.get("champion") == "a2")
    check("the winner is pinned and published",
          (root / "pinned" / "r1_a2").is_dir() and (root / "round1_winner").is_dir())
    check("the revise mode ran NO integration arm",
          (rrec.get("plan") or {}).get("integrated") == [], str((rrec.get("plan") or {}).get("integrated")))
    d = run(["decide", "--root", str(root)])
    check("decide succeeds", d.returncode == 0, (d.stdout or d.stderr)[-500:])
    decision = json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))
    cert = decision.get("certification") or {}
    check("the decision is provisional, not certified",
          cert.get("certified") is False and cert.get("provisional") is True, json.dumps(cert)[:300])
    check("the auto-promoted round is named", cert.get("auto_promoted") == [1], str(cert.get("auto_promoted")))
    check("the verdict says NOT JUDGED", "NOT JUDGED" in (cert.get("notes") or [""])[0]
          or any("auto-promoted" in str(n) for n in cert.get("notes") or []), str(cert.get("notes")))
    check("the clean version is still published",
          (root / "final_clean_version_root").is_dir())


def test_integrate_mode():
    print("\n== integrate mode: the revised candidate's integration arm is promoted ==")
    tmp = scratch("csel_integrate_")
    # pool [a1, a2] -> a2 is member 2 -> i2; mask 0x3 plans both arms.
    root = setup_root(tmp, "integrate", integrators=3)
    r = run_round(root)
    check("the round completes", r.returncode == 0, (r.stdout or r.stderr)[-500:])
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    kinds = {rec.get("kind") for rec in (state.get("runs") or {}).values()}
    check("NO judge session ran", "judge" not in kinds, str(sorted(kinds)))
    check("both integration arms ran", "integrate" in kinds)
    rrec = (state.get("rounds") or {}).get("1") or (state.get("rounds") or {}).get(1) or {}
    check("the promoted version is i2 (the integration of a2)",
          rrec.get("champion") == "i2", str(rrec.get("champion")))
    check("the round is auto-promoted", rrec.get("auto_promoted") is True)
    d = run(["decide", "--root", str(root)])
    check("decide succeeds", d.returncode == 0, (d.stdout or d.stderr)[-500:])
    decision = json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))
    check("the final champion is i2",
          (decision.get("final") or {}).get("champion") == "i2")
    # With NO explicit --integrators, setup enables exactly the promoted arm in
    # every round (including round 3, whose default mask is 0).
    tmp2 = scratch("csel_integrate_default_")
    root2 = tmp2 / "root"
    r2 = run(["setup", "--source", str(make_source(tmp2)), "--root", str(root2),
              "--rounds", "3", "--judges", "1", "--rewrites", "2,0,0", "--revises", "1",
              "--champion-select", "integrate"])
    cfg2 = (json.loads((root2 / "pipeline_config.json").read_text(encoding="utf-8"))
            if (root2 / "pipeline_config.json").is_file() else {})
    masks = [int(x) for x in (cfg2.get("integrators") or [])]
    check("setup enables the promoted arm when no explicit mask was given",
          r2.returncode == 0 and len(masks) == 3
          and (masks[0] >> 3) & 1 and (masks[1] >> 1) & 1 and (masks[2] >> 1) & 1
          and "enables the promoted integration arm" in (r2.stdout + r2.stderr),
          f"rc={r2.returncode} masks={masks} out={(r2.stdout + r2.stderr)[-300:]}")
    # The persisted setter applies the same plan validation/auto-enable.
    tmp3 = scratch("csel_set_command_")
    root3 = tmp3 / "root"
    run(["setup", "--source", str(make_source(tmp3)), "--root", str(root3),
         "--rounds", "1", "--judges", "1", "--rewrites", "0", "--revises", "1",
         "--integrators", "1"])
    r3 = run(["set-champion-select", "integrate", "--root", str(root3)])
    cfg3 = json.loads((root3 / "pipeline_config.json").read_text(encoding="utf-8"))
    check("set-champion-select integrate enables the arm on an existing root",
          r3.returncode == 0 and cfg3.get("champion_select") == "integrate"
          and (int((cfg3.get("integrators") or [0])[0]) >> 1) & 1,
          f"rc={r3.returncode} cfg={cfg3.get('champion_select')} "
          f"masks={cfg3.get('integrators')}")


def test_audit_off():
    print("\n== --no-audit composes with the no-judge modes ==")
    tmp = scratch("csel_noaudit_")
    root = setup_root(tmp, "revise", extra=["--no-audit"])
    r = run_round(root)
    check("the round completes without the audit stage", r.returncode == 0,
          (r.stdout or r.stderr)[-300:])
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    kinds = {rec.get("kind") for rec in (state.get("runs") or {}).values()}
    check("no audit run exists", "audit" not in kinds, str(sorted(kinds)))
    check("revise still wins", ((state.get("rounds") or {}).get("1") or {}).get("champion") == "a2")


def test_refusals():
    print("\n== ambiguous or unplanned promotions are refused at setup ==")
    tmp = scratch("csel_refuse_")
    r = run(["setup", "--source", str(make_source(tmp)), "--root", str(tmp / "root"),
             "--rounds", "1", "--judges", "1", "--rewrites", "0", "--revises", "2",
             "--integrators", "7", "--champion-select", "revise"])
    check("revise with N=2 is refused at setup", r.returncode != 0
          and "needs exactly ONE revise arm" in (r.stdout + r.stderr),
          (r.stdout + r.stderr)[-500:])
    tmp2 = scratch("csel_refuse2_")
    # pool [a1, a2]; mask 0x1 plans i1 (a1) only, never i2 (a2).
    r2 = run(["setup", "--source", str(make_source(tmp2)), "--root", str(tmp2 / "root"),
              "--rounds", "1", "--judges", "1", "--rewrites", "0", "--revises", "1",
              "--integrators", "1", "--champion-select", "integrate"])
    check("integrate with the arm's bit clear is refused at setup", r2.returncode != 0
          and "does not plan that arm" in (r2.stdout + r2.stderr),
          (r2.stdout + r2.stderr)[-500:])


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_helpers()
        test_revise_mode()
        test_integrate_mode()
        test_audit_off()
        test_refusals()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL CHAMPION-SELECTION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

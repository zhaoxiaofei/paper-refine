#!/usr/bin/env python3
"""Regression checks for the 2026-11-14 fix-bugs group M (setup / set-* CLI).

F59   a judge endpoint carrying a userinfo credential (or a malformed port) is
      refused before it can reach the adapter argv
F139  `setup --journal` enforces the one-line/160-character journal rule
F140  `setup --venue-profile` records the FINAL root's module manifest
F141  `set-venue --profile` updates the recorded venue_profiles digest
F142  `adopt-sweep` refuses to rewrite the frozen paper-skills of the running root
F143  `set-venue --journal --strict-venue` refuses a journal/profile mismatch
F144  setup's source/root argument errors exit 2 (usage), not 1
F145  `set-placeholder-file` refuses to change the evidence policy on a root
      with run records without --force
F146  `--clear` + a pattern is a usage error; the clear path writes a run log
F148  a source made of canonical evidence links is materialized
F149  setup's path flags expand `~`
F151  `set-revision-mode` does not validate --journal-feedback for a mode that
      reads no feedback
F152  a failed config save leaves no unselected installed profile behind

Self-contained: every fixture lives under tempfile.mkdtemp(); no network and no
agent session is started.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent
DRIVER = WS / "paper_pipeline.py"
GENERIC_PROFILE = WS / "venue_profiles" / "generic.json"
FAILED = []
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[ok ] " if ok else "[FAIL] ") + name
          + (f"  [{detail}]" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


def _run(argv, *, env=None, cwd=None, timeout=180):
    argv = [str(a) for a in argv]
    if argv and argv[0].endswith(".py"):
        argv = [sys.executable, *argv]
    return subprocess.run(argv, capture_output=True, text=True,
                          env=env or ENV, cwd=str(cwd or WS), timeout=timeout)


def _pin_own_snapshot(root: Path) -> None:
    """Point the recorded origin at the root's own frozen driver.

    Other workers edit the maintained checkout while this suite runs, and the
    loader refuses a mutator on "maintained tree moved on" drift. The defects
    under test are about the RECORDED manifest, which this does not touch.
    """
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    state.setdefault("pipeline", {})["path"] = str(root / "paper_pipeline.py")
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")


def setup_root(tmp: Path, name: str, *extra) -> Path:
    src = tmp / f"src_{name}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "paper.txt").write_text("hello\n", encoding="utf-8")
    root = tmp / name
    r = _run([DRIVER, "setup", "--source", src, "--root", root,
              "--format-fix", "off", *extra])
    if r.returncode != 0:
        raise RuntimeError(f"setup {name} failed ({r.returncode}): "
                           + (r.stdout + r.stderr)[-800:])
    _pin_own_snapshot(root)
    return root


def profile_json(tmp: Path, pid: str) -> Path:
    data = json.loads(GENERIC_PROFILE.read_text(encoding="utf-8"))
    data["id"] = pid
    path = tmp / f"{pid}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def asset_digest(root: Path, name: str = "venue_profiles") -> str:
    code = ("import sys\n"
            f"sys.path.insert(0, {str(root)!r})\n"
            "import paper_pipeline as pp\n"
            "from pathlib import Path\n"
            f"print(pp.asset_dir_digest(Path({str(root)!r}), {name!r}))\n")
    r = _run([sys.executable, "-c", code], cwd=root)
    return (r.stdout or "").strip()


def recorded_modules(root: Path) -> dict:
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    return dict((state.get("pipeline") or {}).get("modules") or {})


def test_f139(tmp: Path) -> None:
    print("\n== F139: setup --journal enforces the journal-name rule ==")
    src = tmp / "f139_src"
    src.mkdir()
    (src / "paper.txt").write_text("hello\n", encoding="utf-8")
    for label, journal in (("newline", "Evil\nJournal"), ("overlong", "J" * 200)):
        root = tmp / f"f139_{label}"
        r = _run([DRIVER, "setup", "--source", src, "--root", root,
                  "--journal", journal, "--format-fix", "off"])
        out = r.stdout + r.stderr
        check(f"F139 setup --journal {label} exits 2",
              r.returncode == 2 and "one line of at most 160" in out,
              f"rc={r.returncode} out={out[-300:]}")
        check(f"F139 setup --journal {label} creates no root", not root.exists())


def test_f140(tmp: Path) -> None:
    print("\n== F140: setup --venue-profile records the final module manifest ==")
    prof = profile_json(tmp, "setup-venue")
    root = setup_root(tmp, "f140_root", "--venue-profile", prof)
    check("F140 the installed profile is in the new root",
          (root / "venue_profiles" / "setup-venue.json").is_file())
    got = recorded_modules(root).get("venue_profiles")
    check("F140 the recorded digest describes the root, not the maintained tree",
          got and got == asset_digest(root), f"recorded={str(got)[:16]}")
    r = _run([root / "paper_pipeline.py", "status", "--root", root])
    out = r.stdout + r.stderr
    check("F140 status does not accuse the fresh root of tampering",
          "does NOT match the module manifest" not in out, out[-400:])


def test_f141(tmp: Path) -> None:
    print("\n== F141: set-venue --profile updates the recorded bundle digest ==")
    root = setup_root(tmp, "f141_root")
    prof = profile_json(tmp, "installed-venue")
    r = _run([root / "paper_pipeline.py", "set-venue", "--root", root,
              "--profile", prof, "installed-venue"])
    out = r.stdout + r.stderr
    check("F141 set-venue --profile succeeds",
          r.returncode == 0 and (root / "venue_profiles" / "installed-venue.json").is_file(),
          out[-400:])
    check("F141 the config records the selected venue",
          json.loads((root / "pipeline_config.json").read_text())["venue"]
          == "installed-venue")
    got = recorded_modules(root).get("venue_profiles")
    check("F141 the recorded digest is recomputed after the install",
          got and got == asset_digest(root), f"recorded={str(got)[:16]}")
    r = _run([root / "paper_pipeline.py", "status", "--root", root])
    out = r.stdout + r.stderr
    check("F141 status does not accuse the root of tampering",
          "does NOT match the module manifest" not in out, out[-400:])


def test_f142(tmp: Path) -> None:
    print("\n== F142: adopt-sweep refuses the running root's frozen skills ==")
    root = setup_root(tmp, "f142_root")
    sweeps = root / "paper-skills/paper-review/references/sweeps.md"
    before = sweeps.read_bytes()
    prop = tmp / "f142_proposal.md"
    prop.write_text(
        "# New sweeps\n\n## M37 -- Figure resolution (proposed)\n"
        "**Purpose:** x\n**Enumeration:** y\n**Artifact:** z\n**Finding rules:** w\n",
        encoding="utf-8")
    r = _run([root / "paper_pipeline.py", "adopt-sweep",
              "--proposals", prop, "--yes"])
    out = r.stdout + r.stderr
    check("F142 adopt-sweep from a root snapshot exits 2",
          r.returncode == 2 and "FROZEN paper-skills" in out, out[-500:])
    check("F142 the frozen sweeps.md is unchanged", sweeps.read_bytes() == before)
    r = _run([root / "paper_pipeline.py", "status", "--root", root])
    out = r.stdout + r.stderr
    check("F142 the root still matches its recorded paper-skills digest",
          "does NOT match the module manifest" not in out, out[-400:])


def test_f143_f146(tmp: Path) -> None:
    print("\n== F143/F146: strict venue + placeholder-file clear ==")
    root = setup_root(tmp, "f143_root")
    before = json.loads((root / "pipeline_config.json").read_text())
    r = _run([root / "paper_pipeline.py", "set-venue", "--root", root,
              "--strict-venue", "--journal", "Totally Different Journal",
              "nature-biotechnology"])
    out = r.stdout + r.stderr
    check("F143 set-venue --journal --strict-venue refuses the mismatch",
          r.returncode == 2 and "--strict-venue:" in out, out[-400:])
    after = json.loads((root / "pipeline_config.json").read_text())
    check("F143 the mismatched journal was not written",
          after.get("journal") == before.get("journal"),
          f"{before.get('journal')!r} -> {after.get('journal')!r}")

    reports = root / "reports"
    logs = lambda: sorted(reports.glob("set-placeholder-file-*.log"))
    r = _run([root / "paper_pipeline.py", "set-placeholder-file", "--root", root,
              "raw_data/*.csv"])
    out = r.stdout + r.stderr
    check("F146 adding a declaration succeeds and logs the invocation",
          r.returncode == 0 and len(logs()) == 1, out[-300:])
    r = _run([root / "paper_pipeline.py", "set-placeholder-file", "--root", root,
              "--clear", "raw_data/*.csv"])
    out = r.stdout + r.stderr
    check("F146 --clear with a pattern is a usage error",
          r.returncode == 2 and "no pattern operand" in out, out[-400:])
    check("F146 the pattern was not silently applied/ignored",
          json.loads((root / "pipeline_config.json").read_text())["placeholder_files"]
          == ["raw_data/*.csv"])
    r = _run([root / "paper_pipeline.py", "set-placeholder-file", "--root", root,
              "--clear"])
    check("F146 clearing writes its own run log",
          r.returncode == 0 and len(logs()) == 2,
          f"logs={[p.name for p in logs()]}")


def test_f144(tmp: Path) -> None:
    print("\n== F144: setup usage errors exit 2 ==")
    src = tmp / "f144_src"
    src.mkdir()
    (src / "paper.txt").write_text("hello\n", encoding="utf-8")
    empty = tmp / "f144_empty"
    empty.mkdir()
    afile = tmp / "f144_afile"
    afile.write_text("x", encoding="utf-8")
    nested = tmp / "f144_nested" / "src"
    nested.mkdir(parents=True)
    (nested / "paper.txt").write_text("hello\n", encoding="utf-8")
    cases = (
        ("source-not-found", [DRIVER, "setup", "--source", tmp / "f144_nope",
                              "--root", tmp / "f144_r1"], "--source directory not found"),
        ("source-empty", [DRIVER, "setup", "--source", empty,
                          "--root", tmp / "f144_r2"], "--source directory is empty"),
        ("root-is-file", [DRIVER, "setup", "--source", src,
                          "--root", afile], "exists and is a FILE"),
        ("nested", [DRIVER, "setup", "--source", nested,
                    "--root", nested / "root"], "must not be nested"),
    )
    for label, argv, needle in cases:
        r = _run(argv)
        out = r.stdout + r.stderr
        check(f"F144 {label} exits 2 with a usage message",
              r.returncode == 2 and needle in out, f"rc={r.returncode} out={out[-250:]}")


def test_f145(tmp: Path) -> None:
    print("\n== F145: set-placeholder-file guards a root with run records ==")
    root = setup_root(tmp, "f145_root")
    state = json.loads((root / "state.json").read_text())
    state["runs"] = {"r1_a1": {"id": "r1_a1", "kind": "a1", "round": 1,
                               "status": "done", "sandbox": "runs/r1_a1",
                               "corpus_digest": "d", "attempts": 1}}
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    r = _run([root / "paper_pipeline.py", "set-placeholder-file", "--root", root,
              "raw_data/*.csv"])
    out = r.stdout + r.stderr
    check("F145 a declaration after a run record is refused",
          r.returncode != 0 and "run record(s)" in out, out[-400:])
    check("F145 the evidence policy was not changed",
          json.loads((root / "pipeline_config.json").read_text())["placeholder_files"] == [])
    # The refusal names `--force`, so the parser must actually accept it: the
    # documented override has to apply the declaration (R01).
    forced = _run([root / "paper_pipeline.py", "set-placeholder-file", "--root", root,
                   "--force", "raw_data/*.csv"])
    forced_out = forced.stdout + forced.stderr
    check("F145 --force is a real option and applies the declaration",
          forced.returncode == 0
          and json.loads((root / "pipeline_config.json").read_text())["placeholder_files"]
          == ["raw_data/*.csv"], f"rc={forced.returncode} out={forced_out[-400:]}")
    cleared = _run([root / "paper_pipeline.py", "set-placeholder-file", "--root", root,
                    "--clear", "--force"])
    check("F145 --force is also honoured by --clear",
          cleared.returncode == 0
          and json.loads((root / "pipeline_config.json").read_text())["placeholder_files"] == [],
          f"rc={cleared.returncode} out={(cleared.stdout + cleared.stderr)[-400:]}")


def test_f148(tmp: Path) -> None:
    print("\n== F148: canonical evidence links are materialized ==")
    owner = tmp / "f148_owner"
    (owner / "non_revised" / "raw_data").mkdir(parents=True)
    (owner / "non_revised" / "raw_data" / "ok.txt").write_text("ok", encoding="utf-8")
    (owner / "state.json").write_text("{}", encoding="utf-8")
    (owner / "pipeline_config.json").write_text("{}", encoding="utf-8")
    linksrc = tmp / "f148_linksrc"
    linksrc.mkdir()
    (linksrc / "raw_data").symlink_to(owner / "non_revised" / "raw_data",
                                      target_is_directory=True)
    root = tmp / "f148_root"
    r = _run([DRIVER, "setup", "--source", linksrc, "--root", root,
              "--format-fix", "off"])
    out = r.stdout + r.stderr
    check("F148 a source of canonical evidence links is accepted",
          r.returncode == 0, out[-500:])
    check("F148 the evidence is materialized into the new root's pristine tree",
          (root / "non_revised" / "raw_data" / "ok.txt").is_file(),
          str(sorted(p.relative_to(root).as_posix()
                     for p in root.rglob("ok.txt"))) if root.exists() else "no root")
    # The containment proof is not weakened: a same-shaped tree that NO run
    # root owns is still refused.
    evil = tmp / "f148_evil" / "non_revised" / "raw_data"
    evil.mkdir(parents=True)
    (evil / "secret.txt").write_text("secret", encoding="utf-8")
    evil_src = tmp / "f148_evil_src"
    evil_src.mkdir()
    (evil_src / "raw_data").symlink_to(evil, target_is_directory=True)
    r = _run([DRIVER, "setup", "--source", evil_src, "--root", tmp / "f148_evil_root",
              "--format-fix", "off"])
    check("F148 a link to a tree no run root owns is still refused",
          r.returncode == 2 and "contains only symlink" in (r.stdout + r.stderr),
          (r.stdout + r.stderr)[-300:])


def test_f149(tmp: Path) -> None:
    print("\n== F149: setup path flags expand ~ ==")
    home = tmp / "f149_home"
    home.mkdir()
    prof = profile_json(home, "home-venue")
    (home / "policy.json").write_text('{"url_style": "plain"}', encoding="utf-8")
    src = tmp / "f149_src"
    src.mkdir()
    (src / "paper.txt").write_text("hello\n", encoding="utf-8")
    root = tmp / "f149_root"
    r = _run([DRIVER, "setup", "--source", src, "--root", root,
              "--venue-profile", "~/home-venue.json",
              "--format-policy", "~/policy.json", "--format-fix", "off"],
             env=dict(ENV, HOME=str(home)))
    out = r.stdout + r.stderr
    cfg = (json.loads((root / "pipeline_config.json").read_text())
           if (root / "pipeline_config.json").is_file() else {})
    check("F149 quoted ~/ paths are expanded",
          r.returncode == 0 and cfg.get("venue") == "home-venue"
          and cfg.get("format_policy") == {"url_style": "plain"}, out[-500:])


def test_f151(tmp: Path) -> None:
    print("\n== F151: no-feedback mode ignores --journal-feedback ==")
    root = setup_root(tmp, "f151_root")
    missing = tmp / "does-not-exist-xyz.txt"
    r = _run([root / "paper_pipeline.py", "set-revision-mode", "init",
              "--root", root, "--journal-feedback", missing])
    out = r.stdout + r.stderr
    check("F151 a stale --journal-feedback does not fail a no-feedback mode",
          r.returncode == 0 and "reads no journal feedback" in out, out[-400:])
    cfg = json.loads((root / "pipeline_config.json").read_text())
    check("F151 the mode was recorded", cfg.get("revision_mode") == "init")
    check("F151 the ignored flag was not stored", "journal_feedback" not in cfg)


def test_f152(tmp: Path) -> None:
    print("\n== F152: a failed config save removes the unselected profile ==")
    root = setup_root(tmp, "f152_root")
    prof = profile_json(tmp, "injected-venue")
    before = json.loads((root / "pipeline_config.json").read_text())["venue"]
    code = f"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, {str(root)!r})
import paper_pipeline as pp
root = Path({str(root)!r})
prof = Path({str(prof)!r})
orig = pp.write_json_atomic
def boom(path, data, *a, **k):
    if Path(path) == root / "pipeline_config.json":
        raise OSError("injected save failure")
    return orig(path, data, *a, **k)
pp.write_json_atomic = boom
ns = argparse.Namespace(root=str(root), strict_venue=False, list=False,
                        show=False, venue="injected-venue", profile=str(prof),
                        article_type=None, journal=None, force=False, json=False)
try:
    pp.cmd_set_venue(ns)
    print("NO-RAISE")
except OSError:
    print("RAISED")
finally:
    pp.write_json_atomic = orig
"""
    r = _run([sys.executable, "-c", code], cwd=root)
    out = r.stdout + r.stderr
    check("F152 the injected config-save failure propagates",
          "RAISED" in out, out[-400:])
    check("F152 no unselected profile is left installed",
          not (root / "venue_profiles" / "injected-venue.json").exists(),
          out[-400:])
    check("F152 the config still names the old venue",
          json.loads((root / "pipeline_config.json").read_text())["venue"] == before)


def test_f59(tmp: Path) -> None:
    print("\n== F59: judge endpoints are validated before reaching argv ==")
    root = setup_root(tmp, "f59_root")
    credential_out = ""
    for label, url, needle in (
            ("credential", "https://user:pw@127.0.0.1:1/v1", "credential"),
            ("malformed-port", "http://host:0/v1", "invalid port")):
        env = dict(ENV, PAPER_JUDGE_AGENT_MODEL=url)
        r = _run([root / "paper_pipeline.py", "run", "--root", root, "--manual"],
                 env=env, timeout=120)
        out = r.stdout + r.stderr
        if label == "credential":
            credential_out = out
        check(f"F59 a judge endpoint with a {label} is refused before any session",
              r.returncode == 2 and "--judge-agent-model:" in out and needle in out,
              f"rc={r.returncode} out={out[-400:]}")
    check("F59 the refusal redacts the endpoint credential",
          "user:pw@" not in credential_out, credential_out[-400:])


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fixbugsM_20261114_"))
    try:
        test_f59(tmp)
        test_f139(tmp)
        test_f140(tmp)
        test_f141(tmp)
        test_f142(tmp)
        test_f143_f146(tmp)
        test_f144(tmp)
        test_f145(tmp)
        test_f148(tmp)
        test_f149(tmp)
        test_f151(tmp)
        test_f152(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(FAILED)} FAILED" if FAILED else "\nall checks passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regression checks for fix_bugs wave 2 (run 2026-11-22-050517).

Every check pins one candidate this wave re-validated on the tree. Each
assertion fails on the unpatched tree and passes after the smallest fix.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp            # noqa: E402
import paper_dsh_runtime as rt         # noqa: E402

FAILS: list[str] = []


def check(label: str, cond, detail="") -> None:
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def _fake_dsh(dirpath: Path) -> None:
    """A minimal `dsh` that answers --version so the installer reaches its checks."""
    dirpath.mkdir(parents=True, exist_ok=True)
    exe = dirpath / "dsh"
    exe.write_text("#!/bin/sh\ncase \"$1\" in --version) echo 1.2.3 ;; esac\nexit 0\n",
                   encoding="utf-8")
    exe.chmod(0o755)


def _installer_env(bin_dir: Path) -> dict:
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    return env


def test_f018_symlinked_profile_dir() -> None:
    print("\n== F018: a symlinked dsh profile directory is refused ==")
    mjs = ROOT / "scripts/install-codex-mcp.mjs"
    if not mjs.is_file():
        check("F018 the installer exists", False, str(mjs))
        return
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        dsh = base / "dsh-home"
        profiles = dsh / "profiles"
        outside = base / "outside"
        profiles.mkdir(parents=True)
        outside.mkdir()
        patch = outside / "cordis.patch.yml"
        original = ("# keep this\n"
                    "# >>> codex-mcp-import (managed block; regenerate with "
                    "install-codex-mcp.mjs) >>>\n"
                    "[]\n"
                    "# <<< codex-mcp-import <<<\n")
        patch.write_text(original, encoding="utf-8")
        (outside / "package.json").write_text(
            json.dumps({"dependencies": {"@deepseek-ai/dsh-mcp-client": "1.2.3"}}),
            encoding="utf-8")
        (profiles / "evil").symlink_to(outside, target_is_directory=True)
        bin_dir = base / "bin"
        _fake_dsh(bin_dir)
        proc = subprocess.run(
            ["node", str(mjs), "--profile", "evil", "--dsh-home", str(dsh),
             "--remove", "--no-verify"],
            cwd=str(ROOT), env=_installer_env(bin_dir), capture_output=True, text=True,
            timeout=60)
        check("F018 a symlinked profile directory is refused before any write",
              proc.returncode != 0 and "outside" in (proc.stderr or ""),
              (proc.returncode, proc.stderr.strip().splitlines()[-1:] if proc.stderr else ""))
        check("F018 the outside patch file stays byte-identical",
              patch.read_text(encoding="utf-8") == original,
              patch.read_text(encoding="utf-8")[:60])
    src = (ROOT / "install_agent_tooling.sh").read_text(encoding="utf-8")
    check("F018 the shell installer realpaths the profile directory",
          "realpath" in src and "profiles_root_real" in src
          and "profile_dir_real" in src)


def test_f022_symlinked_export_destinations() -> None:
    print("\n== F022: export destinations are written through a no-follow temp ==")
    script = ROOT / "scripts/export-test-env.sh"
    src = script.read_text(encoding="utf-8")
    check("F022 the export script has one symlink-safe writer",
          "safe_write()" in src)
    check("F022 the README is not written with a plain cat redirect",
          'cat > "${OUT}/README.md"' not in src)
    check("F022 every public export goes through the safe writer",
          src.count("safe_write ") >= 7,
          src.count("safe_write "))
    if not script.is_file():
        return
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        out = base / "env"
        out.mkdir()
        victim = base / "victim"
        victim.write_text("keep", encoding="utf-8")
        (out / "paper-refine-test.freeze.env_export.yml").symlink_to(victim)
        bin_dir = base / "bin"
        bin_dir.mkdir()
        conda = bin_dir / "conda"
        conda.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  run)\n"
            "    shift\n"
            "    while [ $# -gt 0 ] && [ \"$1\" != python ]; do shift; done\n"
            "    shift\n"
            "    case \"$1\" in\n"
            "      -c) exit 0 ;;\n"
            "      -m) shift; shift; printf 'numpy==1.0\\n'; exit 0 ;;\n"
            "      *)\n"
            "        case \"$1\" in\n"
            "          *env_test_closure.py) out=$2 ;;\n"
            "          *) exit 0 ;;\n"
            "        esac\n"
            "        printf 'numpy==1.0\\n' > \"$out\"; exit 0 ;;\n"
            "    esac ;;\n"
            "  env) printf 'name: paper-refine-test\\nprefix: /tmp/x\\n'; exit 0 ;;\n"
            "  list) printf 'numpy=1.0=pypi_0\\n'; exit 0 ;;\n"
            "esac\n"
            "exit 0\n", encoding="utf-8")
        conda.chmod(0o755)
        env = dict(os.environ)
        env["CONDA_EXE"] = str(conda)
        env["PAPER_REFINE_TEST_ENV"] = "paper-refine-test"
        proc = subprocess.run(["bash", str(script), "--out", str(out)],
                              cwd=str(ROOT), env=env, capture_output=True,
                              text=True, timeout=120)
        check("F022 a symlinked export destination is refused",
              proc.returncode != 0 and "symlink" in (proc.stderr or "").lower(),
              (proc.returncode, (proc.stderr or "").strip().splitlines()[-1:]))
        check("F022 the symlink target is never overwritten",
              victim.read_text(encoding="utf-8") == "keep",
              victim.read_text(encoding="utf-8")[:40])


def test_f023_backup_writers_no_follow() -> None:
    print("\n== F023: backup writers never follow a planted symlink ==")
    mjs = ROOT / "scripts/install-codex-mcp.mjs"
    src = mjs.read_text(encoding="utf-8")
    check("F023 the mjs backup creates with O_EXCL ('wx')",
          'fs.openSync(target, "wx"' in src
          or "fs.openSync(target, 'wx'" in src)
    shell = (ROOT / "install_agent_tooling.sh").read_text(encoding="utf-8")
    # The shell backup writers are `cp -p`-shaped bash, not the embedded node
    # repair JS: assert the ACTUAL backup command, or this check passes on
    # exactly the symlink regression it names (F169).
    check("F023 the shell installer backup creates with O_EXCL",
          "set -o noclobber" in shell and "cp -p --" not in shell)
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        dsh = base / "dsh-home"
        profile = dsh / "profiles" / "headless"
        profile.mkdir(parents=True)
        patch = profile / "cordis.patch.yml"
        patch.write_text("[]\n", encoding="utf-8")
        (profile / "package.json").write_text(
            json.dumps({"dependencies": {"@deepseek-ai/dsh-mcp-client": "1.2.3"}}),
            encoding="utf-8")
        servers = base / "servers.json"
        servers.write_text(json.dumps([{
            "name": "srv",
            "transport": {"type": "stdio", "command": "/bin/echo", "args": []},
        }]), encoding="utf-8")
        # Freeze `new Date()` so the backup name is predictable: the writer takes
        # the stamp from the wall clock, and a planted symlink at that exact name
        # is the reported attack.
        preload = base / "freeze-date.cjs"
        preload.write_text(
            "const RealDate = Date;\n"
            "const fixed = RealDate.parse('2026-11-21T22:00:00.000Z');\n"
            "global.Date = class extends RealDate {\n"
            "  constructor(...args) { if (args.length === 0) super(fixed); else super(...args); }\n"
            "  static now() { return fixed; }\n"
            "};\n", encoding="utf-8")
        stamp = "20261121-220000.000"
        victim = base / "victim"
        (Path(f"{patch}.bak-codex-mcp-{stamp}")).symlink_to(victim)
        victims = [victim]
        bin_dir = base / "bin"
        _fake_dsh(bin_dir)
        proc = subprocess.run(
            ["node", "-r", str(preload), str(mjs),
             "--profile", "headless", "--dsh-home", str(dsh),
             "--servers-json", str(servers), "--no-install", "--no-verify"],
            cwd=str(ROOT), env=_installer_env(bin_dir), capture_output=True,
            text=True, timeout=60)
        check("F023 a dangling symlink is not followed by a backup",
              proc.returncode == 0 and not any(v.is_file() for v in victims),
              [str(v.exists()) for v in victims])
        check("F023 the backup is still written under a real name",
              proc.returncode == 0 and any(
                  p.name.startswith("cordis.patch.yml.bak-codex-mcp-")
                  for p in profile.iterdir() if p.is_file()),
              sorted(p.name for p in profile.iterdir()))


def test_f070_streaming_terminates() -> None:
    print("\n== F070: streaming stops at a terminal turn_end ==")
    code = (
        "import json, os, sys, time\n"
        "sys.stdout.write(json.dumps({'type': 'turn_end', 'status': 'ok'}) + '\\n')\n"
        "sys.stdout.flush()\n"
        "os.close(1)\n"
        "time.sleep(6)\n"
    )
    t0 = time.time()
    rc, failed = rt.run_dsh_streaming(
        [sys.executable, "-c", code], dict(os.environ), "probe")
    elapsed = time.time() - t0
    check("F070 a completed turn is not held by a lingering child", elapsed < 4.5,
          f"{elapsed:.2f}s")
    check("F070 the completed turn is reported as a success", failed is False,
          (rc, failed))


def test_f113_selfcheck_artifact_policy() -> None:
    print("\n== F113: the pre-flight applies the recorded artifact policy ==")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "root"
        (root / "non_revised").mkdir(parents=True)
        (root / "pipeline_config.json").write_text(
            json.dumps({"artifact_policy": "off"}), encoding="utf-8")
        sb = root / "runs" / "r1"
        (sb / pp.REVISED_DIR).mkdir(parents=True)
        (sb / pp.REVISED_DIR / "manuscript.md").write_text("# x\n\nText.\n",
                                                          encoding="utf-8")
        _ok, errs, warns = pp.sandbox_selfcheck(sb, "revise", "r1", 1)
        msg = "no work/R6_language.md"
        check("F113 a policy-off root records the missing pass as a warning",
              not any(msg in e for e in errs) and any(msg in w for w in warns),
              ([e for e in errs if msg in e], [w for w in warns if msg in w]))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "root"
        (root / "non_revised").mkdir(parents=True)
        (root / "pipeline_config.json").write_text(
            json.dumps({"artifact_policy": "on"}), encoding="utf-8")
        sb = root / "runs" / "r1"
        (sb / pp.REVISED_DIR).mkdir(parents=True)
        (sb / pp.REVISED_DIR / "manuscript.md").write_text("# x\n\nText.\n",
                                                          encoding="utf-8")
        _ok, errs, warns = pp.sandbox_selfcheck(sb, "revise", "r1", 1)
        msg = "no work/R6_language.md"
        check("F113 a policy-on root still records the missing pass as an error",
              any(msg in e for e in errs) and not any(msg in w for w in warns),
              ([e for e in errs if msg in e], [w for w in warns if msg in w]))


def _parse_ok(fn, *args):
    """(parsed, error-text) for a parser that exits via `die` on a bad value."""
    try:
        return fn(*args), ""
    except SystemExit as exc:
        return None, f"SystemExit {exc.code}"


def test_f119_python_literal_separators() -> None:
    print("\n== F119: documented Python literal spellings parse ==")
    masks, merr = _parse_ok(pp.parse_round_masks, ["0xFFFF_FFFF"], 1, "--integrators")
    check("F119 an underscore hex mask is one literal", masks == [0xFFFFFFFF],
          (masks, merr))
    counts, cerr = _parse_ok(pp.parse_round_counts, ["1_000"], 2, "--rewrites")
    check("F119 an underscore count is one number, not a list",
          counts == [1000, 1000], (counts, cerr))
    check("F119 comma/space lists still split",
          pp.parse_round_counts(["2, 1"], 2, "--rewrites") == [2, 1])
    check("F119 the historical short-underscore list spelling still splits",
          pp.parse_round_masks(["1_2"], 2, "--integrators") == [1, 2])


def main() -> int:
    test_f018_symlinked_profile_dir()
    test_f022_symlinked_export_destinations()
    test_f023_backup_writers_no_follow()
    test_f070_streaming_terminates()
    test_f113_selfcheck_artifact_policy()
    test_f119_python_literal_separators()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("ALL fix_bugs_20261122_050517_wave2 REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the 2026-11-14 fix-bugs wave, group D.

Each check names the verified finding it proves:
  F35 the Codex->DSH importer refuses to delete a managed block by importing 0
  F36 a failed npm ci / companion install leaves no staging tree behind
  F37 Node < 20 is refused before anything live is switched in
  F41 a failed `pip freeze` fails the environment export instead of writing 0 bytes
  F42 --strict-external fails when an existing checkout cannot be refreshed
  F43 a dirty checkout is reported instead of silently not refreshed

Hermetic: tempfile trees only, no network, no model call.
Run:  conda run -n paper-refine-test python .paper_test/test_fix_bugs_20261114_D.py
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
WS = Path(os.environ.get("PAPER_WS") or HERE.parent)
FAILS = []
SKIPS = []
PASSES = []
CLEAN_ENV_KEYS = (
    "DSH_HOME", "CODEX_HOME", "DSH_PROFILE", "INSTALL_CODEX", "INSTALL_DSH",
    "INSTALL_ZOTERO_MCP", "MCP_TOOLS_DIR", "ZOTERO_BRIDGE_DIR",
    "PAPER_REFINE_DEPS", "PAPER_REFINE_TEST_ENV", "PAPER_REFINE_TEST_PREFIX",
    "CONDA_EXE", "PIP_REQUIRE_VIRTUALENV",
)


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if cond:
        PASSES.append(name)
    else:
        FAILS.append(name)


def skip(name: str, why: str) -> None:
    # A skipped check is NOT a pass: no installer behaviour was asserted. It is
    # reported as `[skip]` and counted separately, never as `[ok ]` (R04).
    print(f"[skip] {name}  -- {why}")
    SKIPS.append(name)


def run(cmd, env=None, cwd=None, timeout=240):
    return subprocess.run(cmd, cwd=str(cwd or WS), env=env,
                          capture_output=True, text=True, timeout=timeout)


def clean_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in CLEAN_ENV_KEYS}
    env.update(extra)
    return env


def write(path: Path, text: str, mode: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    return path


def node_at_least_20() -> str | None:
    node = shutil.which("node")
    if node is None:
        return None
    proc = run([node, "-p", "process.versions.node.split('.')[0]"])
    return node if proc.returncode == 0 and proc.stdout.strip().isdigit() \
        and int(proc.stdout.strip()) >= 20 else None


# ---------------------------------------------------------------------------
# F35: a selection that imports 0 servers must not delete the managed block
# ---------------------------------------------------------------------------
F35_BLOCK = (
    "# profile header\n"
    "# >>> codex-mcp-import (managed block; regenerate with install-codex-mcp.mjs) >>>\n"
    "- insert:\n"
    '    - id: "codex-mcp-docx-compare"\n'
    '      name: "@deepseek-ai/dsh-mcp-client"\n'
    "      config:\n"
    '        transport: "stdio"\n'
    '        serverName: "docx-compare"\n'
    '    - id: "codex-mcp-docx-converter"\n'
    '      name: "@deepseek-ai/dsh-mcp-client"\n'
    "      config:\n"
    '        transport: "stdio"\n'
    '        serverName: "docx-converter"\n'
    "# <<< codex-mcp-import <<<\n"
    "other: 1\n"
)


def _dsh_harness(tmp: Path, name: str) -> tuple[Path, Path, dict]:
    home = tmp / name
    prof = home / "profiles" / "p1"
    prof.mkdir(parents=True)
    write(prof / "cordis.patch.yml", F35_BLOCK)
    write(prof / "package.json", json.dumps(
        {"name": "p1", "dependencies": {"@deepseek-ai/dsh-mcp-client": "0.2.0"}}))
    binp = tmp / "bin"
    write(binp / "dsh", '#!/bin/sh\necho "dsh 0.2.0"\n', 0o755)
    env = clean_env(PATH=f"{binp}{os.pathsep}{os.environ.get('PATH', '')}",
                    CODEX_HOME=str(tmp / "codex"))
    return home, prof, env


def test_f35() -> None:
    node = node_at_least_20()
    if node is None:
        skip("F35 importer refuses a 0-server rewrite", "no Node >= 20 on PATH")
        return
    mjs = str(WS / "scripts" / "install-codex-mcp.mjs")
    with tempfile.TemporaryDirectory(prefix="fbD35_") as scratch:
        tmp = Path(scratch)
        home, prof, env = _dsh_harness(tmp, "home")
        servers = tmp / "servers.json"
        write(servers, json.dumps([{
            "name": "docx-converter", "enabled": False,
            "transport": {"type": "stdio", "command": "node", "args": ["/x.js"]}}]))
        before = (prof / "cordis.patch.yml").read_text(encoding="utf-8")
        proc = run([node, mjs, "--profile", "p1", "--dsh-home", str(home),
                    "--servers-json", str(servers), "--only", "docx-converter",
                    "--no-install", "--no-verify"], env=env)
        after = (prof / "cordis.patch.yml").read_text(encoding="utf-8")
        out = proc.stdout + proc.stderr
        check("F35 a selection that imports 0 servers exits non-zero",
              proc.returncode != 0, f"rc={proc.returncode}")
        check("F35 every skipped server is named in the error",
              "imports 0 server" in out and "docx-converter" in out, out[-300:])
        check("F35 the existing managed rows survive byte-for-byte",
              after == before, after[-200:])

        # A normal import into a fresh profile still works.
        home2, prof2, env2 = _dsh_harness(tmp, "home2")
        servers2 = tmp / "servers-ok.json"
        write(servers2, json.dumps([
            {"name": "docx-converter", "enabled": True,
             "transport": {"type": "stdio", "command": "node", "args": ["/a.js"]}},
            {"name": "docx-compare", "enabled": True,
             "transport": {"type": "stdio", "command": "node", "args": ["/b.js"]}}]))
        proc2 = run([node, mjs, "--profile", "p1", "--dsh-home", str(home2),
                     "--servers-json", str(servers2), "--no-install", "--no-verify"],
                    env=env2)
        text2 = (prof2 / "cordis.patch.yml").read_text(encoding="utf-8")
        check("F35 a normal two-server import still writes both rows",
              proc2.returncode == 0
              and 'serverName: "docx-converter"' in text2
              and 'serverName: "docx-compare"' in text2,
              (proc2.returncode, text2[-200:]))


# ---------------------------------------------------------------------------
# F36: a failed staging step leaves no `.stage.<pid>` tree behind
# ---------------------------------------------------------------------------
def _tooling_env(tmp: Path, binp: Path) -> dict:
    return clean_env(
        HOME=str(tmp / "home"), DSH_HOME=str(tmp / "dsh"),
        CODEX_HOME=str(tmp / "codex"), INSTALL_CODEX="0", INSTALL_DSH="1",
        INSTALL_ZOTERO_MCP="0", MCP_TOOLS_DIR=str(tmp / "tools"),
        PATH=f"{binp}{os.pathsep}{os.environ.get('PATH', '')}")


def _staging_leftovers(tools: Path) -> list[str]:
    return sorted(p.name for p in tools.iterdir() if ".stage." in p.name)


def test_f36() -> None:
    node = node_at_least_20()
    if node is None or shutil.which("bash") is None:
        skip("F36 a failed staging step cleans up", "no Node >= 20 or bash")
        return
    with tempfile.TemporaryDirectory(prefix="fbD36npm_") as scratch:
        tmp = Path(scratch)
        (tmp / "tools").mkdir()
        binp = tmp / "bin"
        write(binp / "npm", "#!/bin/sh\nexit 1\n", 0o755)
        proc = run(["bash", str(WS / "install_agent_tooling.sh")],
                   env=_tooling_env(tmp, binp))
        leftovers = _staging_leftovers(tmp / "tools")
        check("F36 a failed npm ci fails the install", proc.returncode != 0,
              f"rc={proc.returncode}")
        check("F36 a failed npm ci leaves no staging tree", not leftovers, leftovers)

    # The companion-script window: `install` creates the destination, then fails.
    with tempfile.TemporaryDirectory(prefix="fbD36cp_") as scratch:
        tmp = Path(scratch)
        (tmp / "tools").mkdir()
        binp = tmp / "bin"
        write(binp / "npm", "#!/bin/sh\nexit 0\n", 0o755)
        write(binp / "install",
              "#!/bin/sh\nfor last in \"$@\"; do :; done\n: > \"$last\"\nexit 1\n", 0o755)
        proc = run(["bash", str(WS / "install_agent_tooling.sh")],
                   env=_tooling_env(tmp, binp))
        leftovers = _staging_leftovers(tmp / "tools")
        check("F36 a failed companion install fails the install", proc.returncode != 0,
              f"rc={proc.returncode}")
        check("F36 a failed companion install leaves no staging file",
              not leftovers, leftovers)


# ---------------------------------------------------------------------------
# F37: Node < 20 is refused before staging/switch-in in both installers
# ---------------------------------------------------------------------------
def test_f37() -> None:
    if shutil.which("bash") is None:
        skip("F37 old Node is refused", "no bash")
        return
    with tempfile.TemporaryDirectory(prefix="fbD37_") as scratch:
        tmp = Path(scratch)
        binp = tmp / "bin"
        write(binp / "node",
              "#!/bin/sh\ncase \"$1\" in\n  -p) echo 12 ;;\n  -v) echo v12.22.9 ;;\n"
              "  *) exit 1 ;;\nesac\n", 0o755)
        write(binp / "npm", "#!/bin/sh\nexit 0\n", 0o755)
        env = clean_env(
            HOME=str(tmp / "home"), DSH_HOME=str(tmp / "dsh"),
            CODEX_HOME=str(tmp / "codex"), INSTALL_CODEX="0", INSTALL_DSH="1",
            INSTALL_ZOTERO_MCP="0", MCP_TOOLS_DIR=str(tmp / "tools"),
            PATH=f"{binp}{os.pathsep}{os.environ.get('PATH', '')}")
        proc = run(["bash", str(WS / "install_agent_tooling.sh")], env=env)
        out = proc.stdout + proc.stderr
        tools = tmp / "tools"
        installed = sorted(p.name for p in tools.iterdir()) if tools.is_dir() else []
        check("F37 the tooling installer refuses Node 12 before switching in",
              proc.returncode != 0 and "Node >= 20" in out,
              out[-300:])
        check("F37 nothing live was installed by the refused run", not installed,
              installed)

        repo = tmp / "repo"
        repo.mkdir()
        shutil.copy2(WS / "install_dependencies.sh", repo / "install_dependencies.sh")
        proc2 = run(["bash", str(repo / "install_dependencies.sh"),
                     "--no-conda", "--no-external", "--no-agent-tooling"], env=env)
        out2 = proc2.stdout + proc2.stderr
        check("F37 the dependency installer refuses Node 12 at the prerequisite gate",
              proc2.returncode == 2 and "Node >= 20" in out2,
              (proc2.returncode, out2[-300:]))
        check("F37 the refused dependency install writes nothing",
              not (repo / "deps.env").exists()
              and not (repo / "activate-deps.sh").exists())


# ---------------------------------------------------------------------------
# F41: a failed `pip freeze` fails the export instead of writing 0 bytes
# ---------------------------------------------------------------------------
def _fake_conda(path: Path, pip_freeze_ok: bool) -> None:
    body = (
        "#!/bin/sh\n"
        "if [ \"$1\" = \"run\" ]; then\n"
        "  shift 4\n"
        "  if [ \"$1\" = \"-c\" ]; then exit 0; fi\n"
        "  if [ \"$1\" = \"-m\" ]; then\n"
        + ("    echo 'python-docx==1.1.0'\n    exit 0\n"
           if pip_freeze_ok else "    exit 1\n") +
        "  fi\n"
        "  printf 'python-docx==1.1.0\\n' > \"$2\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"env\" ]; then\n"
        "  printf 'name: paper-refine-test\\ndependencies:\\n  - python=3.12\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"list\" ]; then exit 0; fi\n"
        "exit 0\n")
    write(path, body, 0o755)


def test_f41() -> None:
    if shutil.which("bash") is None:
        skip("F41 a failed pip freeze fails the export", "no bash")
        return
    script = str(WS / "scripts" / "export-test-env.sh")
    with tempfile.TemporaryDirectory(prefix="fbD41bad_") as scratch:
        tmp = Path(scratch)
        conda = tmp / "bin" / "conda"
        _fake_conda(conda, pip_freeze_ok=False)
        out_dir = tmp / "out"
        env = clean_env(CONDA_EXE=str(conda))
        proc = run(["bash", script, "--out", str(out_dir)], env=env)
        out = proc.stdout + proc.stderr
        record = out_dir / "paper-refine-test.requirements.list_e.txt"
        check("F41 a broken pip fails the export", proc.returncode != 0,
              f"rc={proc.returncode}")
        check("F41 the failure names pip freeze", "pip freeze" in out, out[-300:])
        check("F41 no empty pip record is written", not record.exists())
    with tempfile.TemporaryDirectory(prefix="fbD41ok_") as scratch:
        tmp = Path(scratch)
        conda = tmp / "bin" / "conda"
        _fake_conda(conda, pip_freeze_ok=True)
        out_dir = tmp / "out"
        env = clean_env(CONDA_EXE=str(conda))
        proc = run(["bash", script, "--out", str(out_dir)], env=env)
        record = out_dir / "paper-refine-test.requirements.list_e.txt"
        check("F41 a working pip still exports the wheel record",
              proc.returncode == 0 and record.is_file()
              and "python-docx==1.1.0" in record.read_text(encoding="utf-8"),
              (proc.returncode, (proc.stdout + proc.stderr)[-300:]))


# ---------------------------------------------------------------------------
# F42/F43: the external-checkout refresh branch
# ---------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), "-c", "user.email=t@example.invalid",
                "-c", "user.name=test", *args], timeout=60)


def _git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    write(path / "file.txt", "v1\n")
    _git(path, "init", "-q")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "first")
    _git(path, "branch", "-M", "main")


def _deps_fixture(tmp: Path) -> tuple[Path, Path, dict]:
    repo = tmp / "repo"
    repo.mkdir()
    shutil.copy2(WS / "install_dependencies.sh", repo / "install_dependencies.sh")
    agent_common = repo / "agent-common" / "agent_common"
    agent_common.mkdir(parents=True)
    for name in ("model_runtime.py", "llm_retry.py", "llm_policy.json",
                 "model_catalog.json"):
        write(agent_common / name, "")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    deps = tmp / "deps"
    for name in ("zotero-use", "openai-plugins"):
        _git_repo(deps / name)
    bridge = tmp / "bridge"
    _git_repo(bridge)
    env = clean_env(
        PAPER_REFINE_DEPS=str(deps), MCP_TOOLS_DIR=str(tmp / "tools"),
        ZOTERO_BRIDGE_DIR=str(bridge), HOME=str(tmp / "home"),
        GIT_TERMINAL_PROMPT="0", PATH=os.environ.get("PATH", ""))
    return repo, deps, env


def _deps_run(repo: Path, env: dict, strict: bool) -> subprocess.CompletedProcess:
    cmd = ["bash", str(repo / "install_dependencies.sh"), "--no-conda",
           "--no-node", "--no-agent-tooling", "--no-zot-cli"]
    if strict:
        cmd.append("--strict-external")
    return run(cmd, env=env)


def test_f42() -> None:
    if shutil.which("git") is None or shutil.which("bash") is None:
        skip("F42 strict-external covers a failed refresh", "no git/bash")
        return
    with tempfile.TemporaryDirectory(prefix="fbD42_") as scratch:
        tmp = Path(scratch)
        repo, deps, env = _deps_fixture(tmp)
        for name in ("zotero-use", "openai-plugins"):
            _git(deps / name, "remote", "add", "origin", str(tmp / "no-such-remote"))
        plain = _deps_run(repo, env, strict=False)
        plain_out = plain.stdout + plain.stderr
        check("F42 without --strict-external a failed refresh warns and succeeds",
              plain.returncode == 0 and "could not fetch zotero-use" in plain_out,
              (plain.returncode, plain_out[-300:]))
        strict = _deps_run(repo, env, strict=True)
        strict_out = strict.stdout + strict.stderr
        check("F42 --strict-external fails when an existing checkout cannot be refreshed",
              strict.returncode != 0
              and "could not refresh external checkout: zotero-use" in strict_out,
              (strict.returncode, strict_out[-400:]))


def test_f43() -> None:
    if shutil.which("git") is None or shutil.which("bash") is None:
        skip("F43 a dirty checkout is reported", "no git/bash")
        return
    with tempfile.TemporaryDirectory(prefix="fbD43_") as scratch:
        tmp = Path(scratch)
        repo, deps, env = _deps_fixture(tmp)
        dirty = deps / "zotero-use"
        _git(dirty, "remote", "add", "origin", str(tmp / "no-such-remote"))
        write(dirty / "file.txt", "v1\nlocal edit\n")
        old_head = _git(dirty, "rev-parse", "HEAD").stdout.strip()
        plain = _deps_run(repo, env, strict=False)
        plain_out = plain.stdout + plain.stderr
        installed = deps / "INSTALLED.json"
        recorded = ""
        if installed.is_file():
            recorded = json.loads(installed.read_text(encoding="utf-8"))["repos"] \
                .get("zotero-use", {}).get("commit", "")
        check("F43 a dirty checkout is reported as not refreshed",
              plain.returncode == 0
              and f"not refreshing zotero-use: local modifications in {dirty}" in plain_out,
              (plain.returncode, plain_out[-400:]))
        check("F43 the recorded commit is the un-refreshed (dirty) HEAD",
              recorded == old_head, f"{recorded} != {old_head}")
        strict = _deps_run(repo, env, strict=True)
        strict_out = strict.stdout + strict.stderr
        check("F43 --strict-external refuses a dirty (un-refreshable) external checkout",
              strict.returncode != 0
              and "external checkout has local modifications: zotero-use" in strict_out,
              (strict.returncode, strict_out[-400:]))


def main() -> int:
    test_f35()
    test_f36()
    test_f37()
    test_f41()
    test_f42()
    test_f43()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        print(f"GROUP-D: {len(PASSES)} passed / {len(SKIPS)} skipped / "
              f"{len(FAILS)} failed")
        return 1
    print(f"GROUP-D: {len(PASSES)} passed / {len(SKIPS)} skipped / 0 failed")
    if SKIPS:
        print("NOT ALL GROUP-D FIX CHECKS WERE ASSERTED: " + "; ".join(SKIPS))
        return 0
    print("ALL GROUP-D FIX CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

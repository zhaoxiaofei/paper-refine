#!/usr/bin/env python3
"""The dependency installer and checkout-relative dependency paths.

Run:  python3 .paper_test/test_install_dependencies.py

Asserts:
  * `install_dependencies.sh` is executable, documents the install plan, and a
    `--dry-run` with the optional parts disabled succeeds without writing;
  * the installer and the runtime prompts contain no machine-specific absolute
    path (`/mnt/d/software/plugins`, `/home/<user>`);
  * the stage prompts route Zotero work through `$ZOTERO_SKILL` and the
    harness skill directories (`$CODEX_HOME`, `$DSH_HOME`) instead of a baked
    home-directory path;
  * the shipped skills and their standalone prompts use the same variable, not
    a machine path;
  * the recorded conda exports carry no machine `prefix:` line;
  * the generated dependency environment is ignored by git.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def main() -> int:
    script = WS / "install_dependencies.sh"
    check("the dependency installer exists", script.is_file())
    check("the dependency installer is executable", os.access(script, os.X_OK))
    text = read(script)
    check("it documents the conda/npm/git/Zotero parts",
          all(word in text for word in
              ("conda", "npm ci", "git clone", "zotero-use", "codex-zotero-bridge",
               "zotero_mcp.py", "zotero_pair")))
    check("it writes checkout-relative dependency paths",
          "RELATIVE" in text and "deps.env" in text and "activate-deps.sh" in text)
    check("it never hard-codes a machine path",
          not re.search(r"/mnt/d/software|/home/[A-Za-z0-9_.-]+/", text))

    help_proc = subprocess.run([str(script), "--help"], capture_output=True,
                               text=True, timeout=30)
    check("--help succeeds", help_proc.returncode == 0,
          (help_proc.stdout + help_proc.stderr)[-200:])
    check("--help documents the skip switches",
          all(flag in help_proc.stdout for flag in
              ("--dry-run", "--offline", "--no-conda", "--no-external",
               "--no-agent-tooling", "--no-zotero-mcp")))

    deps_env = WS / "deps.env"
    before = deps_env.read_bytes() if deps_env.is_file() else None
    dry = subprocess.run([str(script), "--dry-run", "--no-conda", "--no-node",
                          "--no-external"], capture_output=True, text=True, timeout=60)
    check("a minimal --dry-run succeeds and changes nothing",
          dry.returncode == 0 and "install complete" in (dry.stdout + dry.stderr),
          (dry.stdout + dry.stderr)[-300:])
    after = deps_env.read_bytes() if deps_env.is_file() else None
    check("the dry-run does not create or modify deps.env", after == before)

    # A fresh clone has .git but an empty agent-common/ (the submodule is not
    # initialized). The documented --dry-run contract is "print the plan,
    # change nothing", so it must name the planned update and exit 0 without
    # treating the still-missing files as a failed install.
    with tempfile.TemporaryDirectory(prefix="installer-fresh-clone-") as scratch:
        clone = Path(scratch)
        shutil.copy2(script, clone / "install_dependencies.sh")
        (clone / ".git").mkdir()
        (clone / "agent-common").mkdir()
        fresh = subprocess.run(
            [str(clone / "install_dependencies.sh"), "--dry-run", "--no-conda",
             "--no-node", "--no-external", "--no-agent-tooling"],
            capture_output=True, text=True, timeout=60)
        fresh_out = fresh.stdout + fresh.stderr
        check("a fresh-clone --dry-run plans the submodule update and succeeds",
              fresh.returncode == 0
              and "submodule update --init --recursive" in fresh_out
              and "install complete" in fresh_out,
              fresh_out[-300:])

    prompt_sources = [WS / "paper_pipeline_parts" / "p02_journal_modes.py",
                      WS / "paper_pipeline_parts" / "p03_prompts.py"]
    for source in prompt_sources:
        body = read(source)
        check(f"{source.name} has no machine-specific Zotero path",
              not re.search(r"/mnt/d/software/plugins|/home/[A-Za-z0-9_.-]+/", body))
    prelude = read(WS / "paper_pipeline_parts" / "p00_prelude.py")
    check("the frozen module list carries the model catalog data file",
          "model_catalog.json" in prelude)
    prompts = read(prompt_sources[1])
    check("the stage prompts name the exported Zotero helper",
          "$ZOTERO_SKILL" in prompts)
    check("the stage prompts use the harness skill directories",
          "$CODEX_HOME/skills" in prompts and "$DSH_HOME/skills" in prompts)
    check("the stage prompts still pin the fallback route",
          "FALLBACK when the `zot` command and the MCP service" in prompts)

    for rel in ("paper-skills/paper-review/SKILL.md",
                "paper-skills/paper-revise/SKILL.md",
                "paper-skills/README.md",
                "paper-skills/prompts/identify_issues.prompt.md",
                "paper-skills/prompts/adress_issues.prompt.md"):
        body = read(WS / rel)
        check(f"{rel} has no machine-specific Zotero path",
              not re.search(r"/mnt/d/software/plugins|/home/[A-Za-z0-9_.-]+/", body))
        check(f"{rel} names $ZOTERO_SKILL", "$ZOTERO_SKILL" in body)

    for path in sorted((WS / "env").glob("*.yml")):
        check(f"{path.name} carries no machine prefix", "prefix:" not in read(path))

    ignore = read(WS / ".gitignore")
    for entry in ("external/", "deps.env", "activate-deps.sh"):
        check(f".gitignore ignores {entry}", entry in ignore)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL DEPENDENCY-INSTALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

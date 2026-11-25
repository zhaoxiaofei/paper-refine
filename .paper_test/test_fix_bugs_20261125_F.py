#!/usr/bin/env python3
"""Regression checks for group F of the 2026-11-25 02:31 fix-bugs wave.

Every check pins one assigned finding (F036-F053) and was written to FAIL on the
pre-patch tree. The suite is hermetic: temp dirs only, no network, no Word/Office,
no real $HOME configuration and no installer is run for real.

Run:  python3 .paper_test/test_fix_bugs_20261125_F.py
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)

FAILS: list[str] = []
TMPDIRS: list[Path] = []


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name: str, cond, detail="") -> bool:
    ok = bool(cond)
    print(f"[{'ok ' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)
    return ok


def run(cmd, *, cwd=None, env=None, timeout=180, input_text=None):
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, timeout=timeout,
                          input=input_text, capture_output=True, text=True)


def cleanup() -> None:
    for tmp in TMPDIRS:
        for p in [tmp, *tmp.rglob("*")]:
            if p.is_symlink():
                # F041 shims the host tools into ``minbin``; chmod follows the link and
                # would stamp 0644 on the real interpreter this suite runs under.
                continue
            with contextlib.suppress(OSError):
                if p.is_dir():
                    p.chmod(0o755)
                else:
                    p.chmod(0o644)
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# F036/F040: export-test-env.sh producer failure and file modes
# --------------------------------------------------------------------------
def fake_conda_export(tmp: Path, *, export_ok: bool) -> Path:
    """A conda stand-in for export-test-env.sh (never a real environment)."""
    tpl = r'''#!/usr/bin/env bash
set -u
mode="$FAKE_CONDA_MODE"
case "$1" in
  run)
    # `conda run <select> python <...>`: existence probe, pip freeze, closure.
    shift
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -n|-p) shift 2 ;;
        python) shift; break ;;
        *) shift ;;
      esac
    done
    if [ "$#" -gt 0 ] && [ "$1" = "-c" ]; then exit 0; fi
    if [ "$#" -gt 0 ] && [ "$1" = "-m" ]; then
      printf 'numpy==1.0\nrequests==2.0\n' ; exit 0
    fi
    # env_test_closure.py <dest>
    if [ "$#" -gt 0 ]; then printf 'python-docx==1.2.0\n' > "$1"; fi
    exit 0
    ;;
  env)
    if [ "$2" = export ]; then
      if [ "$mode" = fail ]; then
        echo "CondaError: simulated export failure" >&2
        exit 1
      fi
      printf 'name: paper-refine-test\nchannels:\n  - defaults\ndependencies:\n  - python=3.12\nprefix: /home/someone/miniconda3/envs/paper-refine-test\n'
      exit 0
    fi
    if [ "$2" = remove ] || [ "$2" = create ] || [ "$2" = list ]; then exit 0; fi
    exit 0
    ;;
  list)
    printf '# packages in environment\n#\npython=3.12=pypi_0\nnumpy==1.0=pypi_0\n'
    exit 0
    ;;
  info)
    printf '%s\n' "$FAKE_CONDA_BASE"
    exit 0
    ;;
esac
exit 0
'''
    conda = tmp / "bin" / "conda"
    conda.parent.mkdir(parents=True, exist_ok=True)
    conda.write_text(tpl)
    conda.chmod(0o755)
    return conda


def export_env(tmp: Path, conda: Path, mode: str) -> dict:
    env = dict(os.environ)
    env.update(CONDA_EXE=str(conda), FAKE_CONDA_MODE=mode,
               FAKE_CONDA_BASE=str(tmp / "conda-base"),
               PAPER_REFINE_TEST_ENV="paper-refine-test")
    env.pop("PAPER_REFINE_TEST_PREFIX", None)
    return env


def script_copy(tmp: Path, name: str) -> Path:
    d = tmp / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "..").resolve()
    src = WS / "scripts" / name
    dst = d / name
    shutil.copy2(src, dst)
    return dst


def test_F036() -> None:
    print("\n== F036: a failed `conda env export` must not publish an empty file ==")
    tmp = scratch("F036_")
    conda = fake_conda_export(tmp, export_ok=False)
    out = tmp / "out"
    out.mkdir()
    good = out / "paper-refine-test.freeze.env_export.yml"
    good.write_text("GOOD EXPORT\n")
    script = script_copy(tmp, "export-test-env.sh")
    proc = run(["bash", script, "--out", str(out)], cwd=tmp,
               env=export_env(tmp, conda, "fail"))
    body = good.read_text() if good.exists() else "<missing>"
    check("F036 a failing producer keeps the previous export intact",
          proc.returncode != 0 and body == "GOOD EXPORT\n",
          f"exit={proc.returncode} content={body!r} stderr={proc.stderr.strip()[-160:]}")


def test_F040() -> None:
    print("\n== F040: regenerated env/ artefacts keep the committed 0644 mode ==")
    tmp = scratch("F040_")
    conda = fake_conda_export(tmp, export_ok=True)
    out = tmp / "out"
    out.mkdir()
    script = script_copy(tmp, "export-test-env.sh")
    proc = run(["bash", script, "--out", str(out)], cwd=tmp,
               env=export_env(tmp, conda, "ok"))
    target = out / "paper-refine-test.freeze.env_export.yml"
    readme = out / "README.md"
    modes = {p.name: oct(stat.S_IMODE(p.stat().st_mode)) for p in (target, readme)
             if p.exists()}
    check("F040 the regenerated export and README are world-readable (0644)",
          proc.returncode == 0
          and modes.get(target.name) == "0o644"
          and modes.get(readme.name) == "0o644",
          f"exit={proc.returncode} modes={modes} stderr={proc.stderr.strip()[-200:]}")


# --------------------------------------------------------------------------
# F037: create-test-env.sh --recreate on a non-conda prefix directory
# --------------------------------------------------------------------------
def test_F037() -> None:
    print("\n== F037: --recreate repairs a prefix directory conda does not know ==")
    tmp = scratch("F037_")
    conda = tmp / "bin" / "conda"
    conda.parent.mkdir(parents=True, exist_ok=True)
    conda.write_text(r'''#!/usr/bin/env bash
set -u
case "$1" in
  run)
    case "$*" in
      *"import sys"*) exit 1 ;;       # the prefix's Python does not run
      *) exit 0 ;;
    esac ;;
  env)
    case "$2" in
      remove)
        echo "EnvironmentLocationNotFound: Not a conda environment: $4" >&2
        exit 1 ;;
      create)
        # create the prefix conda would create
        for a in "$@"; do :; done
        exit 0 ;;
    esac
    exit 0 ;;
  info) printf '%s\n' "$FAKE_CONDA_BASE"; exit 0 ;;
  create)
    # `conda create -y -p <prefix> python=...`
    exit 0 ;;
esac
exit 0
''')
    conda.chmod(0o755)
    base = tmp / "conda-base"
    (base / "envs").mkdir(parents=True)
    prefix = tmp / "prefix"
    prefix.mkdir()                       # exists, empty, not a conda environment
    exports = tmp / "exports"
    exports.mkdir()
    (exports / "paper-refine-test.freeze.env_export.from_history.yml").write_text(
        "name: paper-refine-test\ndependencies:\n  - python=3.12\n")
    script = script_copy(tmp, "create-test-env.sh")
    env = dict(os.environ)
    env.update(CONDA_EXE=str(conda), FAKE_CONDA_BASE=str(base),
               PAPER_REFINE_TEST_PREFIX=str(prefix),
               PAPER_REFINE_TEST_ENV="paper-refine-test",
               PAPER_REFINE_TEST_EXPORT_DIR=str(exports),
               CONDA_PKGS_DIRS=str(tmp / "pkgs"),
               CONDA_ENVS_PATH=str(tmp / "envs"),
               PIP_CACHE_DIR=str(tmp / "pip"))
    env.pop("PAPER_REFINE_TEST_PYTHON", None)
    proc = run(["bash", script, "--recreate"], cwd=tmp, env=env)
    check("F037 --recreate removes a non-conda prefix instead of aborting",
          proc.returncode == 0 and not prefix.exists(),
          f"exit={proc.returncode} prefix_exists={prefix.exists()} "
          f"stderr={proc.stderr.strip()[-200:]} stdout={proc.stdout.strip()[-160:]}")


# --------------------------------------------------------------------------
# F038: extract the real Claude stale branch and run it hermetically
# --------------------------------------------------------------------------
def extract_bash_block(text: str, start: str, end_strip: str) -> str:
    lines = text.splitlines()
    i = next(k for k, line in enumerate(lines) if line == start)
    body = []
    for line in lines[i + 1:]:
        if line.strip() == end_strip:
            return "\n".join(body)
        body.append(line[4:] if line.startswith("    ") else line)
    raise AssertionError(f"unterminated block starting {start!r}")


def test_F038() -> None:
    print("\n== F038: a failed Claude `mcp add` restores the removed row ==")
    src = (WS / "install_agent_tooling.sh").read_text()
    func_lines = src.splitlines()
    start = next(k for k, line in enumerate(func_lines)
                 if line == "        backup_claude_config() {")
    func = []
    for line in func_lines[start:]:
        func.append(line[8:] if line.startswith("        ") else line)
        if line.strip() == "}" and len(func) > 1:
            break
    func_text = "\n".join(func)
    try:
        stale = extract_bash_block(src, "                stale)", ";;")
    except (StopIteration, AssertionError) as exc:
        check("F038 the Claude stale branch can be exercised", False, str(exc))
        return
    tmp = scratch("F038_")
    home = tmp / "home"
    home.mkdir()
    cfg = home / ".claude.json"
    original = '{"mcpServers":{"docx-compare":{"command":"node","args":["/old/index.js"]}}}\n'
    cfg.write_text(original)
    backup = tmp / "backup"
    backup.mkdir()
    fake_cli = tmp / "fake-claude.sh"
    fake_cli.write_text(r'''#!/usr/bin/env bash
case "$2" in
  remove) printf '{"mcpServers":{}}\n' > "$HOME/.claude.json"; exit 0 ;;
  add) printf '{"mcpServers":{}}\n' > "$HOME/.claude.json"
       echo "simulated add failure" >&2; exit 1 ;;
esac
exit 0
''')
    fake_cli.chmod(0o755)
    script = tmp / "harness.sh"
    script.write_text("#!/usr/bin/env bash\nset -euo pipefail\n"
                      f"claude_backup_dir={backup}\n"
                      f"claude_cli={fake_cli}\n"
                      "claude_config_backed_up=0\n"
                      "name=docx-compare\ncommand=/bin/true\nscript=/opt/mcp/index.js\n"
                      + func_text + "\n"
                      + stale + "\n")
    env = dict(os.environ, HOME=str(home))
    proc = run(["bash", script], cwd=tmp, env=env)
    body = cfg.read_text()
    check("F038 a failed replacement add restores the pre-change Claude config",
          proc.returncode != 0 and body == original and "restored" in proc.stderr,
          f"exit={proc.returncode} restored={body == original} "
          f"stderr={proc.stderr.strip()[-200:]}")


# --------------------------------------------------------------------------
# F039: the snapshot prune must not match an operator directory
# --------------------------------------------------------------------------
def test_F039() -> None:
    print("\n== F039: the snapshot prune skips non-snapshot directory names ==")
    src = (WS / "install_agent_tooling.sh").read_text().splitlines()
    start = next(k for k, line in enumerate(src)
                 if line.startswith("    for _stale in \"${tool_path}\"-"))
    body = []
    for line in src[start:]:
        body.append(line[4:] if line.startswith("    ") else line)
        if line.strip() == "done":
            break
    tmp = scratch("F039_")
    tool = tmp / "mcp-docx-compare"
    tool.mkdir()
    keep_dir = tmp / "mcp-docx-compare-2026-1122-notes"
    keep_dir.mkdir()
    (keep_dir / "operator.txt").write_text("mine\n")
    keep_backup = tmp / "mcp-docx-compare-backup"
    keep_backup.mkdir()
    snapshot = tmp / "mcp-docx-compare-2026-1122-abcdef0"
    snapshot.mkdir()
    script = tmp / "harness.sh"
    script.write_text("#!/usr/bin/env bash\nset -euo pipefail\n"
                      f"tool_path={tool}\n" + "\n".join(body) + "\n")
    proc = run(["bash", script], cwd=tmp)
    check("F039 a date-like operator directory survives the prune while the "
          "installer snapshot is removed",
          proc.returncode == 0 and keep_dir.exists() and keep_dir.joinpath("operator.txt").exists()
          and keep_backup.exists() and not snapshot.exists(),
          f"exit={proc.returncode} keep={keep_dir.exists()} "
          f"backup={keep_backup.exists()} snapshot={snapshot.exists()} "
          f"stderr={proc.stderr.strip()[-160:]}")


# --------------------------------------------------------------------------
# F041: install_dependencies.sh --dry-run without npm
# --------------------------------------------------------------------------
def test_F041() -> None:
    print("\n== F041: --dry-run reports a missing npm as a note, not a failure ==")
    tmp = scratch("F041_")
    bindir = tmp / "minbin"
    bindir.mkdir()
    needed = ["bash", "git", "python3", "node", "dirname", "sed", "cat", "env",
              "grep", "date", "uname", "head", "basename", "realpath", "tr"]
    for name in needed:
        found = shutil.which(name)
        if found:
            with contextlib.suppress(OSError):
                (bindir / name).symlink_to(found)
    env = {"PATH": str(bindir), "HOME": str(tmp / "home"),
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    (tmp / "home").mkdir()
    proc = run(["bash", str(WS / "install_dependencies.sh"), "--dry-run",
                "--no-conda", "--no-external"],
               cwd=tmp, env=env)
    check("F041 a dry run on a machine without Node/npm prints the plan and exits 0",
          proc.returncode == 0,
          f"exit={proc.returncode} stderr={proc.stderr.strip()[-300:]}")


# --------------------------------------------------------------------------
# Node harnesses for the MCP servers (stub SDK, real server sources copied)
# --------------------------------------------------------------------------
MCP_STUBS = {
    "node_modules/@modelcontextprotocol/server/package.json":
        '{"name":"@modelcontextprotocol/server","version":"0.0.0","type":"module",'
        '"exports":{".":"./index.js","./stdio":"./stdio.js"}}',
    "node_modules/@modelcontextprotocol/server/index.js":
        'export class McpServer {\n'
        '  constructor() { this.tools = new Map(); }\n'
        '  registerTool(name, opts, handler) { this.tools.set(name, { opts, handler }); }\n'
        '}\n',
    "node_modules/@modelcontextprotocol/server/stdio.js":
        'export function serveStdio(factory) { globalThis.__mcpFactory = factory; }\n',
    "node_modules/zod/package.json":
        '{"name":"zod","version":"0.0.0","type":"module",'
        '"exports":{"./v4":"./v4.js"}}',
    "node_modules/zod/v4.js":
        'const str = { describe: () => str, optional: () => str };\n'
        'export const object = (shape) => ({ shape });\n'
        'export const string = () => str;\n'
        'export const z = { object, string };\n',
}


def mcp_area(tmp: Path, server: str) -> Path:
    area = tmp / "area"
    for rel, body in MCP_STUBS.items():
        p = area / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    files = (["index.js", "containment.mjs", "derived-output.mjs", "run-child.mjs"]
             if server == "compare"
             else ["index.js", "containment.mjs", "run-child.mjs", "in-flight.mjs"])
    src = WS / ("mcp-docx-compare" if server == "compare" else "mcp-docx-converter")
    for name in files:
        shutil.copy2(src / name, area / name)
    return area


def harness_script(area: Path, server: str, call: dict) -> Path:
    runner = area / "harness.mjs"
    tool = "compare_docx" if server == "compare" else "convert_docx_to_pdf"
    runner.write_text(
        "const factory = (await import('./index.js'));\n"
        "void factory;\n"
        f"const server = globalThis.__mcpFactory();\n"
        f"const entry = server.tools.get({json.dumps(tool)});\n"
        f"const payload = {json.dumps(call)};\n"
        "try {\n"
        "  const res = await entry.handler(payload);\n"
        "  console.log(JSON.stringify(res));\n"
        "} catch (err) {\n"
        "  console.log(JSON.stringify({ threw: String(err && err.message || err) }));\n"
        "}\n")
    return runner


def fake_script(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env bash\nset -u\n" + body)
    path.chmod(0o755)
    return path


def test_F045_default_output() -> None:
    print("\n== F045: the comparer passes the documented default output to the child ==")
    tmp = scratch("F045a_")
    area = mcp_area(tmp, "compare")
    args = tmp / "args.txt"
    fake = fake_script(tmp / "fake-compare.sh",
                       'for a in "$@"; do printf "%s\\n" "$a" >> "$ARGS_FILE"; done\n'
                       'exit 0\n')
    orig = area / "a.docx"
    rev = area / "b.docx"
    orig.write_text("x")
    rev.write_text("y")
    runner = harness_script(area, "compare",
                            {"originalPath": str(orig), "revisedPath": str(rev)})
    env = dict(os.environ, DOCXCOMPARE_SH=str(fake), ARGS_FILE=str(args))
    env.pop("DOCX_MCP_ALLOWED_ROOTS", None)
    proc = run(["node", runner], cwd=area, env=env)
    got = args.read_text().split() if args.exists() else []
    res = {}
    with contextlib.suppress(Exception):
        res = json.loads(proc.stdout.strip().splitlines()[-1])
    check("F045 an omitted outputPath still yields a concrete argv output "
          "(so the Windows-pid file can be named)",
          proc.returncode == 0 and len(got) == 3
          and got[2].endswith("a-vs-b-redline.docx")
          and not res.get("isError"),
          f"argv={got} res={res} stderr={proc.stderr.strip()[-200:]}")


def test_F045_pidless_kill() -> None:
    print("\n== F045: a WSL tree kill with no recorded Windows pids is incomplete ==")
    tmp = scratch("F045b_")
    mod = WS / "mcp-docx-compare" / "run-child.mjs"
    probe = tmp / "probe.mjs"
    missing = tmp / "no-such-pidfile"
    probe.write_text(
        f"import {{ killProcessTree }} from {json.dumps(str(mod))};\n"
        "const r = killProcessTree({ pid: 999999, kill() {} }, {\n"
        "  platform: 'linux', detached: true, wsl: true,\n"
        f"  windowsPidFile: {json.dumps(str(missing))},\n"
        "  kill() {}, spawnSync() { return { status: 128 }; },\n"
        "});\n"
        "console.log(JSON.stringify(r));\n")
    proc = run(["node", probe], cwd=tmp)
    try:
        res = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        res = {}
    check("F045 a requested-but-unreadable Windows pid file is reported incomplete",
          res.get("ok") is False and "no Windows pids" in str(res.get("error", "")),
          f"result={res} stderr={proc.stderr.strip()[-200:]}")


def test_F046() -> None:
    print("\n== F046: a directory swap during the run cannot silently redirect the write ==")
    tmp = scratch("F046_")
    area = mcp_area(tmp, "compare")
    allowed = tmp / "allowed"
    outside = tmp / "outside"
    (allowed / "out").mkdir(parents=True)
    outside.mkdir()
    args = tmp / "args.txt"
    fake = fake_script(tmp / "fake-compare.sh",
                       'for a in "$@"; do printf "%s\\n" "$a" >> "$ARGS_FILE"; done\n'
                       'out="$3"\n'
                       'd="$(dirname -- "$out")"\n'
                       'mv -- "$d" "$d-moved"\n'
                       'ln -s -- "$OUTSIDE" "$d"\n'
                       'printf redline > "$out"\n'
                       'exit 0\n')
    orig = allowed / "a.docx"
    rev = allowed / "b.docx"
    orig.write_text("x")
    rev.write_text("y")
    out = allowed / "out" / "redline.docx"
    runner = harness_script(area, "compare",
                            {"originalPath": str(orig), "revisedPath": str(rev),
                             "outputPath": str(out)})
    env = dict(os.environ, DOCXCOMPARE_SH=str(fake), ARGS_FILE=str(args),
               OUTSIDE=str(outside), DOCX_MCP_ALLOWED_ROOTS=str(allowed))
    proc = run(["node", runner], cwd=area, env=env)
    res = {}
    with contextlib.suppress(Exception):
        res = json.loads(proc.stdout.strip().splitlines()[-1])
    stray = outside / "redline.docx"
    check("F046 an output redirected outside DOCX_MCP_ALLOWED_ROOTS is refused "
          "and the stray file is removed",
          proc.returncode == 0 and res.get("isError") is True and not stray.exists(),
          f"res={res} stray={stray.exists()} stderr={proc.stderr.strip()[-200:]}")

    # The converter carries the same write path for its derived PDF.
    ctmp = scratch("F046c_")
    carea = mcp_area(ctmp, "converter")
    callowed = ctmp / "allowed"
    coutside = ctmp / "outside"
    callowed.mkdir()
    coutside.mkdir()
    cargs = ctmp / "args.txt"
    cfake = fake_script(ctmp / "fake-convert.sh",
                        'for a in "$@"; do printf "%s\\n" "$a" >> "$ARGS_FILE"; done\n'
                        'out="$2"\n'
                        'd="$(dirname -- "$out")"\n'
                        'mv -- "$d" "$d-moved"\n'
                        'ln -s -- "$OUTSIDE" "$d"\n'
                        'printf pdf > "$out"\n'
                        'exit 0\n')
    cdoc = callowed / "paper.docx"
    cdoc.write_text("x")
    crunner = harness_script(carea, "converter", {"docxPath": str(cdoc)})
    cenv = dict(os.environ, DOCX2PDF_SH=str(cfake), ARGS_FILE=str(cargs),
                OUTSIDE=str(coutside), DOCX_MCP_ALLOWED_ROOTS=str(callowed))
    cproc = run(["node", crunner], cwd=carea, env=cenv)
    cres = {}
    with contextlib.suppress(Exception):
        cres = json.loads(cproc.stdout.strip().splitlines()[-1])
    cstray = coutside / "paper.pdf"
    check("F046 the converter refuses a redirected derived PDF and removes it",
          cproc.returncode == 0 and cres.get("isError") is True and not cstray.exists(),
          f"res={cres} stray={cstray.exists()} stderr={cproc.stderr.strip()[-200:]}")


def test_F047() -> None:
    print("\n== F047: a failed tree kill does not leak the child's pipes ==")
    tmp = scratch("F047_")
    mods = [WS / "mcp-docx-compare" / "run-child.mjs",
            WS / "mcp-docx-converter" / "run-child.mjs"]
    results = {}
    for label, mod in (("compare", mods[0]), ("converter", mods[1])):
        results[label] = f047_probe(tmp / label, mod)
    leaked_c = results["compare"].get("compare_leaked")
    leaked_v = results["converter"].get("converter_leaked")
    check("F047 eight failed-kill timeouts leak no file descriptors (both servers)",
          leaked_c is not None and leaked_v is not None
          and leaked_c <= 1 and leaked_v <= 1,
          f"compare={results['compare']} converter={results['converter']}")


def f047_probe(tmp: Path, mod: Path) -> dict:
    tmp.mkdir(parents=True, exist_ok=True)
    probe = tmp / "probe.mjs"
    probe.write_text(
        f"import {{ runFile }} from {json.dumps(str(mod))};\n"
        "import { readdirSync, readFileSync } from 'node:fs';\n"
        "const fds = () => readdirSync('/proc/self/fd').length;\n"
        "const before = fds();\n"
        "const pids = [];\n"
        "for (let i = 0; i < 8; i += 1) {\n"
        "  const pidFile = `${process.env.PROBE_DIR}/pid-${i}`;\n"
        "  try {\n"
        "    await runFile(process.execPath,\n"
        "      ['-e', `require('fs').writeFileSync(${JSON.stringify(pidFile)},"
        " String(process.pid)); setTimeout(() => {}, 60000)`],\n"
        "      { timeout: 60, killGraceMs: 60,\n"
        "        killTree: () => ({ ok: false, error: 'simulated denial' }) });\n"
        "  } catch {}\n"
        "  try { pids.push(Number(readFileSync(pidFile, 'utf8'))); } catch {}\n"
        "}\n"
        "const after = fds();\n"
        "for (const p of pids) { try { process.kill(p, 9); } catch {} }\n"
        "console.log(JSON.stringify({ before, after, pids }));\n")
    env = dict(os.environ, PROBE_DIR=str(tmp))
    proc = run(["node", probe], cwd=tmp, env=env)
    try:
        res = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        res = {}
    leaked = int(res.get("after", 0)) - int(res.get("before", 0))
    res[f"{tmp.name}_leaked"] = leaked
    return res


# --------------------------------------------------------------------------
# F048/F049/F050/F051: scripts/install-codex-mcp.mjs
# --------------------------------------------------------------------------
def codex_installer_area(tmp: Path) -> tuple[Path, Path]:
    area = tmp / "area"
    area.mkdir()
    dsh = area / "dshhome"
    prof = dsh / "profiles" / "headless"
    prof.mkdir(parents=True)
    (prof / "package.json").write_text(
        '{"name":"headless","dependencies":'
        '{"@deepseek-ai/dsh-mcp-client":"0.2.0-rc.2"}}')
    (prof / "cordis.patch.yml").write_text("[]\n")
    fake = area / "bin" / "dsh"
    fake.parent.mkdir()
    fake.write_text('#!/usr/bin/env bash\n'
                    'case "$1" in --version) echo "0.2.0-rc.2"; exit 0;; esac\n'
                    'exit 0\n')
    fake.chmod(0o755)
    return area, dsh


def run_codex_installer(area: Path, dsh: Path, servers_json: Path, *extra,
                        patch: str | None = None) -> subprocess.CompletedProcess:
    if patch is not None:
        (dsh / "profiles" / "headless" / "cordis.patch.yml").write_text(patch)
    env = dict(os.environ, PATH=f"{area / 'bin'}:{os.environ.get('PATH', '')}")
    # The installer defaults --profile to $DSH_PROFILE, and this fixture only
    # creates the "headless" profile.  A developer shell (or a DSH session)
    # exports DSH_PROFILE=web, which must not leak into the hermetic fixture.
    env.pop("DSH_PROFILE", None)
    env.pop("DSH_HOME", None)
    return run(["node", str(WS / "scripts" / "install-codex-mcp.mjs"),
                "--dsh-home", str(dsh), "--servers-json", str(servers_json),
                "--no-install", "--no-verify", *extra], cwd=area, env=env)


KEPT_ROW = (
    "- insert:\n"
    '    - id: "codex-mcp-x"\n'
    '      name: "@deepseek-ai/dsh-mcp-client"\n'
    "      config:\n"
    '        transport: "stdio"\n'
    '        serverName: "y"\n'
    '        command: "/opt/kept-server"\n')


def block_file(rows: str) -> str:
    return ("# >>> codex-mcp-import (managed block; regenerate with "
            "install-codex-mcp.mjs) >>>\n" + rows
            + "# <<< codex-mcp-import <<<\n")


def test_F048() -> None:
    print("\n== F048: --merge seeds used ids/names with the kept rows ==")
    tmp = scratch("F048_")
    area, dsh = codex_installer_area(tmp)
    servers = area / "servers_x.json"
    servers.write_text(json.dumps(
        [{"name": "x", "enabled": True,
          "transport": {"type": "stdio", "command": "/bin/true"}}]))
    proc = run_codex_installer(area, dsh, servers, "--merge",
                               patch=block_file(KEPT_ROW))
    text = (dsh / "profiles" / "headless" / "cordis.patch.yml").read_text()
    ids = re.findall(r'^\s*-\s+id:\s*"([^"]+)"', text, re.M)
    kept_ok = "/opt/kept-server" in text
    check("F048 a merged run gives the new row a fresh id and keeps the kept row",
          proc.returncode == 0 and len(ids) == len(set(ids)) and kept_ok,
          f"exit={proc.returncode} ids={ids} kept={kept_ok} "
          f"stderr={proc.stderr.strip()[-200:]}")


def test_F049() -> None:
    print("\n== F049: a same-line comment on an empty `[]` profile survives ==")
    tmp = scratch("F049_")
    area, dsh = codex_installer_area(tmp)
    servers = area / "servers_x.json"
    servers.write_text(json.dumps(
        [{"name": "x", "enabled": True,
          "transport": {"type": "stdio", "command": "/bin/true"}}]))
    proc = run_codex_installer(area, dsh, servers,
                               patch="[]  # my profile note\n")
    text = (dsh / "profiles" / "headless" / "cordis.patch.yml").read_text()
    check("F049 the comment outside the markers is preserved",
          proc.returncode == 0 and "# my profile note" in text,
          f"exit={proc.returncode} text={text[:180]!r} "
          f"stderr={proc.stderr.strip()[-160:]}")


def test_F050() -> None:
    print("\n== F050: an up-to-date re-run still enforces the documented 0600 ==")
    tmp = scratch("F050_")
    area, dsh = codex_installer_area(tmp)
    patch_file = dsh / "profiles" / "headless" / "cordis.patch.yml"
    servers = area / "servers_x.json"
    servers.write_text(json.dumps(
        [{"name": "x", "enabled": True,
          "transport": {"type": "stdio", "command": "/bin/true"}}]))
    first = run_codex_installer(area, dsh, servers, patch="[]\n")
    patch_file.chmod(0o644)
    second = run_codex_installer(area, dsh, servers)
    mode = oct(stat.S_IMODE(patch_file.stat().st_mode))
    check("F050 the no-op branch sets the patch to 0600",
          first.returncode == 0 and second.returncode == 0 and mode == "0o600",
          f"exit={second.returncode} mode={mode} out={second.stdout.strip()[-160:]}")


def test_F051() -> None:
    print("\n== F051: an overflowing tool_timeout_sec never emits Infinity ==")
    tmp = scratch("F051_")
    area, dsh = codex_installer_area(tmp)
    servers = area / "servers_timeout.json"
    servers.write_text(json.dumps(
        [{"name": "slow", "enabled": True, "tool_timeout_sec": 1e308,
          "transport": {"type": "stdio", "command": "/bin/true"}}]))
    proc = run_codex_installer(area, dsh, servers)
    text = (dsh / "profiles" / "headless" / "cordis.patch.yml").read_text()
    check("F051 the non-finite timeout is warned about and omitted",
          proc.returncode == 0 and "Infinity" not in text
          and "toolCallTimeoutMs" not in text
          and "tool_timeout_sec" in proc.stderr,
          f"exit={proc.returncode} text={text[-200:]!r} "
          f"stderr={proc.stderr.strip()[-200:]}")


# --------------------------------------------------------------------------
# F052: the converter's overflow check must fail on the F173 mutation
# --------------------------------------------------------------------------
def test_F052() -> None:
    print("\n== F052: the converter overflow test catches a removed grace timer ==")
    tmp = scratch("F052_")
    src = WS / "mcp-docx-converter"
    work = tmp / "mut"
    work.mkdir()
    shutil.copy2(src / "run-child.mjs", work / "run-child.mjs")
    shutil.copy2(src / "run-child.test.mjs", work / "run-child.test.mjs")
    code = (work / "run-child.mjs").read_text()
    anchor = code.index("const error = new Error(overflow);")
    start = code.rindex("graceTimer = setTimeout(() => {", 0, anchor)
    end = code.index("}, killGraceMs);", anchor) + len("}, killGraceMs);")
    tail = code[end:]
    if tail.startswith("\n        if (typeof graceTimer.unref === 'function') graceTimer.unref();"):
        end += len("\n        if (typeof graceTimer.unref === 'function') graceTimer.unref();")
    mutated = code[:start] + code[end:]
    (work / "run-child.mjs").write_text(mutated)
    proc = run(["node", "run-child.test.mjs"], cwd=work)
    plain = run(["node", "run-child.test.mjs"], cwd=src)
    check("F052 the test FAILS when the overflow grace timer is deleted "
          "(and passes unmutated)",
          proc.returncode != 0
          and "overflow settled only when the child exited" in proc.stdout
          and plain.returncode == 0,
          f"mutated_exit={proc.returncode} plain_exit={plain.returncode} "
          f"mutated_tail={proc.stdout.strip()[-220:]}")


# --------------------------------------------------------------------------
# F053: case-distinct output on a case-sensitive filesystem
# --------------------------------------------------------------------------
def test_F053() -> None:
    print("\n== F053: a case-distinct output is not refused as an input ==")
    tmp = scratch("F053_")
    area = mcp_area(tmp, "compare")
    args = tmp / "args.txt"
    fake = fake_script(tmp / "fake-compare.sh",
                       'for a in "$@"; do printf "%s\\n" "$a" >> "$ARGS_FILE"; done\n'
                       'exit 0\n')
    lower = area / "report.docx"
    upper = area / "Report.docx"
    lower.write_text("A")
    fake_rev = area / "rev.docx"
    fake_rev.write_text("B")
    runner = harness_script(area, "compare",
                            {"originalPath": str(lower), "revisedPath": str(fake_rev),
                             "outputPath": str(upper)})
    env = dict(os.environ, DOCXCOMPARE_SH=str(fake), ARGS_FILE=str(args))
    env.pop("DOCX_MCP_ALLOWED_ROOTS", None)
    proc = run(["node", runner], cwd=area, env=env)
    res = {}
    with contextlib.suppress(Exception):
        res = json.loads(proc.stdout.strip().splitlines()[-1])
    got = args.read_text().split() if args.exists() else []
    check("F053 report.docx and Report.docx are distinct on a case-sensitive fs",
          proc.returncode == 0 and res.get("isError") is not True
          and str(upper) in got,
          f"res={res} argv={got} stderr={proc.stderr.strip()[-200:]}")


def main() -> int:
    tests = [
        test_F036, test_F037, test_F038, test_F039, test_F040, test_F041,
        test_F045_default_output, test_F045_pidless_kill, test_F046, test_F047,
        test_F048, test_F049, test_F050, test_F051, test_F052, test_F053,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:  # a crashing check is a failing check
            import traceback
            traceback.print_exc()
            check(f"{test.__name__} ran", False, f"{type(exc).__name__}: {exc}")
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) FAILED:")
        for name in FAILS:
            print(f"  - {name}")
    else:
        print("All group-F checks PASSED")
    cleanup()
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

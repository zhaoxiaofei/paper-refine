#!/usr/bin/env python3
"""Regressions for the 2026-11-17 fix-bugs wave 2 (verified-findings set).

One check per candidate this wave confirmed and patched:
  F144  a declaration matching only `logs/*.txt` is not honoured
  F163  the revision-audit/repair prompts carry the run's hand-off rule
  F192  the in-process redline engine is bounded by a timeout
  F208  a Claude Code machine gets its skills/MCP rows installed
  F222  a UTF-16 auxiliary DOCX part is decoded (and re-encoded) correctly
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
import paper_pipeline as pp                                        # noqa: E402
import paper_docx_format as f                                      # noqa: E402

FAILS = []
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def check(name, ok, detail=""):
    print(("[ok ] " if ok else "[FAIL] ") + name + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def pkg(files, readme=None):
    d = Path(tempfile.mkdtemp())
    if readme:
        (d / "README.md").write_text(readme, encoding="utf-8")
    for name, data in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            p.write_text(data, encoding="utf-8")
        else:
            p.write_bytes(data)
    return d


def docx_bytes(parts):
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_f144_declaration_plausibility():
    print("\n== F144: a declaration may not drop the package's manuscript ==")
    root = pkg({"logs/run.txt": "log line\n", "main.docx": b"PK\x03\x04junk"},
               "Only `logs/*.txt` will be submitted to the journal.\n")
    got = pp.declared_submission_set(root)
    check("F144 a logs-only declaration is ignored", got["declared"] is False, str(got))
    check("F144 the ignored declaration narrows nothing",
          got.get("files") == [], str(got))

    root = pkg({"main.docx": b"PK\x03\x04junk", "cover.pdf": b"%PDF"},
               "Only `main*.docx` will be submitted.\n")
    got = pp.declared_submission_set(root)
    check("F144 a real manuscript declaration is still honoured",
          got["declared"] is True and got["files"] == ["main.docx"], str(got))

    root = pkg({"main.docx": b"PK\x03\x04junk", "Figure1.pdf": b"%PDF"},
               "Only `Figure*.pdf` will be submitted.\n")
    got = pp.declared_submission_set(root)
    check("F144 a display-item declaration is not manuscript evidence",
          got["declared"] is False, str(got))

    root = pkg({"paper.md": "# Paper\n\nProse.\n", "logs/run.txt": "log\n"},
               "Only `logs/*.txt` will be submitted.\n")
    got = pp.declared_submission_set(root)
    check("F144 a log in a plain-text package is not manuscript evidence",
          got["declared"] is False, str(got))


def test_f163_revision_prompt_handoff():
    print("\n== F163: revision audit/repair prompts carry the hand-off rule ==")
    sb = Path(tempfile.mkdtemp())
    audit = pp.revision_audit_prompt(sb, "r1_revision_audit", 1,
                                     author_to_complete="readme")
    repair = pp.revision_repair_prompt(sb, "r1_repair", 1, 1,
                                       author_to_complete="readme")
    check("F163 the audit prompt carries the PIPELINE HAND-OFF rule",
          "PIPELINE HAND-OFF ITEMS" in audit)
    check("F163 the repair prompt carries the PIPELINE HAND-OFF rule",
          "PIPELINE HAND-OFF ITEMS" in repair)
    check("F163 the readme policy is named as the run's policy",
          "--author-to-complete readme" in audit and "PIPELINE HAND-OFF ITEMS" in repair)
    off = pp.revision_repair_prompt(sb, "r1_repair", 1, 1,
                                    author_to_complete="off")
    check("F163 the off policy is named, not silently rewritten to readme",
          "--author-to-complete off" in off and "PIPELINE HAND-OFF ITEMS" in off)


def test_f192_inproc_timeout():
    print("\n== F192: the in-process redline engine is bounded ==")
    fake = types.ModuleType("python_redlines")

    class Good:
        def __init__(self, *a):
            pass

        def run_redline(self, *a):
            return (b"REDLINED", "", "")

    fake.DocxodusEngine = Good
    sys.modules["python_redlines"] = fake
    out = Path(tempfile.mkdtemp()) / "out.docx"
    try:
        got = pp._redlines_inproc(Path("/tmp/b.docx"), Path("/tmp/r.docx"), out)
    finally:
        sys.modules.pop("python_redlines", None)
    check("F192 a healthy in-process engine still produces the file",
          got["ok"] and out.read_bytes() == b"REDLINED", str(got))

    fake = types.ModuleType("python_redlines")

    class Hung:
        def __init__(self, *a):
            pass

        def run_redline(self, *a):
            time.sleep(30)

    fake.DocxodusEngine = Hung
    sys.modules["python_redlines"] = fake
    old = pp.INPROC_REDLINE_TIMEOUT
    pp.INPROC_REDLINE_TIMEOUT = 0.25
    started = time.time()
    try:
        got = pp._redlines_inproc(Path("/tmp/b.docx"), Path("/tmp/r.docx"),
                                  Path(tempfile.mkdtemp()) / "out.docx")
    finally:
        pp.INPROC_REDLINE_TIMEOUT = old
        sys.modules.pop("python_redlines", None)
    elapsed = time.time() - started
    check("F192 a hung engine does not hang the pass",
          got["ok"] is False and "timeout" in got["detail"] and elapsed < 5,
          f"{got} elapsed={elapsed:.2f}")


def _fake_claude(bin_dir: Path) -> None:
    """A `claude` CLI stand-in with mcp get/add/remove and a JSON state file."""
    script = r'''#!/usr/bin/env python3
import json, os, sys
state = os.environ["FAKE_CLAUDE_STATE"]
try:
    db = json.load(open(state))
except Exception:
    db = {}

def options(rest):
    scope = None
    out = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--scope", "-s") and i + 1 < len(rest):
            scope = rest[i + 1]
            i += 2
            continue
        out.append(a)
        i += 1
    return scope, out

args = sys.argv[1:]
if args[:2] == ["mcp", "get"] and len(args) == 3:
    row = db.get(args[2])
    if not row:
        print("No MCP server found with name: " + args[2])
        sys.exit(1)
    print(args[2] + ":")
    print("  Command: " + row[0])
    print("  Args: " + " ".join(row[1:]))
    sys.exit(0)
if args[:2] == ["mcp", "add"]:
    _scope, rest = options(args[2:])
    name, rest = rest[0], rest[1:]
    if rest and rest[0] == "--":
        rest = rest[1:]
    db[name] = rest
    json.dump(db, open(state, "w"))
    print("Added " + name)
    sys.exit(0)
if args[:2] == ["mcp", "remove"]:
    _scope, rest = options(args[2:])
    db.pop(rest[0], None)
    json.dump(db, open(state, "w"))
    print("Removed " + rest[0])
    sys.exit(0)
print("unsupported fake claude call: " + repr(args), file=sys.stderr)
sys.exit(2)
'''
    p = bin_dir / "claude"
    p.write_text(script, encoding="utf-8")
    p.chmod(0o755)


def test_f208_claude_tooling():
    print("\n== F208: a Claude Code machine gets skills and MCP rows ==")
    if shutil.which("bash") is None:
        print("[skip] F208 no bash")
        return
    node = shutil.which("node")
    if node is None:
        print("[skip] F208 no node")
        return
    root = Path(tempfile.mkdtemp())
    home = root / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    tools = root / "tools"
    tools.mkdir()
    bin_dir = root / "bin"
    bin_dir.mkdir()
    _fake_claude(bin_dir)
    (bin_dir / "npm").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "npm").chmod(0o755)
    state = root / "claude_state.json"
    state.write_text("{}", encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k not in ("INSTALL_CODEX", "INSTALL_DSH", "INSTALL_CLAUDE", "CLAUDE_HOME")}
    env.update(HOME=str(home), INSTALL_CODEX="0", INSTALL_DSH="0",
               INSTALL_CLAUDE="1", INSTALL_ZOTERO_MCP="0",
               MCP_TOOLS_DIR=str(tools), FAKE_CLAUDE_STATE=str(state),
               PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
               PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(["bash", "install_agent_tooling.sh"], cwd=str(WS), env=env,
                          capture_output=True, text=True, timeout=300)
    skills = {name: (home / ".claude" / "skills" / name / "SKILL.md").is_file()
              for name in ("paper-review", "paper-revise")}
    rows = json.loads(state.read_text(encoding="utf-8"))
    check("F208 the installer accepts a Claude Code-only machine",
          proc.returncode == 0, (proc.stdout + proc.stderr)[-400:])
    check("F208 both skills land in $CLAUDE_HOME/skills", all(skills.values()), str(skills))
    check("F208 both docx MCP rows are registered with claude",
          set(rows) == {"docx-compare", "docx-converter"}, str(rows))
    check("F208 the registered command is the deployed server",
          all("mcp-docx-" in " ".join(v) for v in rows.values()), str(rows))


def test_f222_utf16_aux_part():
    print("\n== F222: a UTF-16 auxiliary part is read and rewritten as UTF-16 ==")
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>Body text.</w:t>'
           f'</w:r></w:p></w:body></w:document>')
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              f'<w:styles xmlns:w="{W_NS}"><w:style w:type="paragraph" w:default="1" '
              f'w:styleId="Normal"><w:name w:val="Normal"/></w:style></w:styles>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.'
          'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    footnotes = (f'<?xml version="1.0" encoding="UTF-16" standalone="yes"?>'
                 f'<w:footnotes xmlns:w="{W_NS}"><w:footnote w:id="1"><w:p>'
                 f'<w:r><w:t>Note </w:t></w:r>'
                 f'<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                 f'<w:r><w:instrText> ADDIN ZOTERO_ITEM CSL_CITATION {{"citationID":"abc"}} '
                 f'</w:instrText></w:r>'
                 f'<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                 f'<w:r><w:t>[1]</w:t></w:r>'
                 f'<w:r><w:fldChar w:fldCharType="end"/></w:r>'
                 f'</w:p></w:footnote></w:footnotes>')
    src = Path(tempfile.mkdtemp()) / "in.docx"
    src.write_bytes(docx_bytes({
        "[Content_Types].xml": ct,
        "word/document.xml": doc,
        "word/styles.xml": styles,
        "word/footnotes.xml": footnotes.encode("utf-16"),
    }))
    raw = zipfile.ZipFile(src).read("word/footnotes.xml")
    lost = raw.decode("utf-8", "replace")
    _new, removed = f._unlink_fields(lost)
    check("F222 the pre-fix utf-8 read cannot see the field",
          "ZOTERO_ITEM" not in lost and removed == 0, str(removed))

    policy = dict(f.POLICY_DEFAULTS)
    policy.update(unlink_zotero_fields=True, refresh_zotero_fields=False,
                  repair_reference_entries=False)
    out = src.with_name("out.docx")
    res = f.fix_package(src, out, policy)
    got = zipfile.ZipFile(out).read("word/footnotes.xml") if out.exists() else b""
    check("F222 the UTF-16 footnote field is flattened",
          res.get("ok") and b"ZOTERO_ITEM" not in got, str(res.get("error"))[:300])
    check("F222 the rewritten part keeps its UTF-16 encoding", got[:2] == b"\xff\xfe",
          repr(got[:8]))


def test_r04_judges_restore() -> None:
    """R04: a scoped mode truncates judges to one round; leaving restores it."""
    print("\n== R04: leaving a scoped mode restores the per-round judges plan ==")
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "src"
    (src / "raw_data").mkdir(parents=True)
    (src / "manuscript.txt").write_text("Body text follows here.\n", encoding="utf-8")

    def cli(*argv):
        return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"),
                               *map(str, argv)], capture_output=True, text=True,
                              timeout=300)

    root = tmp / "root"
    r = cli("setup", "--source", str(src), "--root", str(root),
            "--rounds", "3", "--judges", "2,1,1")
    check("R04 setup accepts a per-round judges plan", r.returncode == 0,
          (r.stdout + r.stderr)[-300:])
    r = cli("set-revision-mode", "major", "--root", str(root))
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("R04 the scoped mode truncates judges to its one round",
          r.returncode == 0 and list(cfg.get("judges") or []) == [2]
          and list((cfg.get("scoped_mode_restore") or {}).get("judges") or []) == [2, 1, 1],
          json.dumps({k: cfg.get(k) for k in ("rounds", "judges")}))
    r = cli("set-revision-mode", "continue", "--root", str(root))
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("R04 leaving the mode restores the operator's judges plan",
          r.returncode == 0 and list(cfg.get("judges") or []) == [2, 1, 1],
          json.dumps({k: cfg.get(k) for k in ("rounds", "judges")}))

    # The setup --revision-mode path saves the plan before it truncates judges.
    root = tmp / "root2"
    r = cli("setup", "--source", str(src), "--root", str(root),
            "--rounds", "3", "--judges", "2,1,1", "--revision-mode", "major")
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("R04 scoped setup saves the judges plan before truncating it",
          r.returncode == 0 and list(cfg.get("judges") or []) == [2]
          and list((cfg.get("scoped_mode_restore") or {}).get("judges") or []) == [2, 1, 1],
          json.dumps({k: cfg.get(k) for k in ("rounds", "judges")}))
    r = cli("set-revision-mode", "continue", "--root", str(root))
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("R04 leaving a scoped setup restores the operator's judges plan",
          r.returncode == 0 and list(cfg.get("judges") or []) == [2, 1, 1],
          json.dumps({k: cfg.get(k) for k in ("rounds", "judges")}))


def test_r06_per_version_report() -> None:
    """R06: a per-version panel never reaches a report as the literal None."""
    print("\n== R06: a per-version score set is never reported as None ==")
    check("R06 the label names the per-version map for a selector round",
          pp.scores_per_version_label({"scores_per_version": None})
          == "per-version (see `scores_per_version_by_version`)"
          and pp.scores_per_version_label({"scores_per_version": 4}) == "4")
    root = Path(tempfile.mkdtemp())
    (root / "reports").mkdir()
    (root / "runs").mkdir()
    ctx = pp.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": 2, "rewrites": 1, "revises": 0, "source": "r06"}
    ctx.state = {"version": pp.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "original_digest": "d", "config": ctx.cfg}

    def stat():
        return {"n": 2, "expected_n": 2, "complete": True, "median": 0.0, "mean": 0.0,
                "iqr": 0.0, "vs_original": 0.0, "vs_base": 0.0,
                "anti_regression_ok": True, "judges_seen": 1, "judges_expected": 1,
                "author_placeholders": 0, "own_counts": {}, "received_counts": {}}

    agg = {"round": 1, "field": ["orig", "w1"], "field_size": 2,
           "scores_per_version": None,
           "scores_per_version_by_version": {"orig": 1, "w1": 1},
           "stats": {"orig": stat(), "w1": stat()},
           "diagnostics": {"sheets_used": 3, "sheets_expected": 4},
           "issue_census": {}, "score_rows": [], "issue_rows": [],
           "dedup_mode": None, "anti_regression_rule": None,
           "base_id": "A1", "base_rep": "orig", "generated": "now"}
    stored = {"champion": "w1", "pin_path": "pinned/r1_w1", "pin_digest": "d" * 64,
              "winner_dir": "round1_winner", "plan": {}}
    final = {"round": 1, "stored": stored, "pin": {"digest": "d" * 64}}
    text = pp.build_decision_report(
        ctx, [{"round": 1, "agg": agg, "sel": {}, "stored": stored}],
        {"pristine_ok": True, "pristine_detail": "ok", "pinned_errors": [],
         "recovery": []}, [], final)
    check("R06 the decision report names the per-version map and never None",
          "None" not in text and "scores_per_version_by_version" in text,
          [ln for ln in text.splitlines() if "None" in ln][:2])
    import inspect
    check("R06 the console summary uses the same per-version label",
          "scores/version={scores_per_version_label(rd['agg'])}"
          in inspect.getsource(pp._cmd_decide_locked))


def main() -> int:
    test_f144_declaration_plausibility()
    test_f163_revision_prompt_handoff()
    test_f192_inproc_timeout()
    test_f208_claude_tooling()
    test_f222_utf16_aux_part()
    test_r04_judges_restore()
    test_r06_per_version_report()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

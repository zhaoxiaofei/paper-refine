#!/usr/bin/env python3
"""The 2026-10-31 18:00 fix-bugs wave: verified defect regressions.

Run:  python3 .paper_test/test_fix_bugs_20261031_180026.py

Every check corresponds to a finding the two independent verify-findings passes
kept (F05, F07, F13, F14, F17, F18, F20, F21, F23, F24, F25, F26, F30, F31,
F36-F39, F53, F54, F73, F76, F79). F15 was re-validated and is NOT a bug: the
bare-id-list naming shape is documented in the revise prompt and pinned by
`.paper_test/test_fix_bugs_20261027_120003.py` / `test_llm_stochastic_failures.py`.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
CLI = [sys.executable, str(WS / "paper_pipeline.py")]
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


pp = load("fix_bugs_pipeline_1031", WS / "paper_pipeline.py")
fmt = load("fix_bugs_formatter_1031", WS / "paper_docx_format.py")


def run(args, **kw):
    return subprocess.run(CLI + args, capture_output=True, text=True, timeout=1200, **kw)


def make_source(tmp: Path) -> Path:
    src = tmp / "source"
    src.mkdir(parents=True)
    (src / "manuscript.md").write_text(
        "# Title\n\nA stub manuscript for the 2026-10-31 fix-bugs regression.\n",
        encoding="utf-8")
    return src


def setup_root(tmp: Path, *extra) -> Path:
    root = tmp / "root"
    r = run(["setup", "--source", str(make_source(tmp)), "--root", str(root),
             "--rounds", "1", "--judges", "1", *extra])
    check(f"setup {list(extra)} succeeds", r.returncode == 0,
          (r.stderr or r.stdout)[-300:])
    return root


# ---------------------------------------------------------------------------
# F05 -- a symlinked staged .official/.manuscripts directory is not published
# ---------------------------------------------------------------------------
def test_f05() -> None:
    print("\n== F05: publish_add_venue_staging refuses a symlinked staged tree ==")
    base = scratch("f05_")
    sb = base / "sb"
    (sb / "store").mkdir(parents=True)
    dest = base / "store"
    dest.mkdir()
    outside = base / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET OFFICIAL", encoding="utf-8")
    os.symlink(outside, sb / "store" / "tv.official")
    out = pp.publish_add_venue_staging(sb, dest, "tv")
    check("F05 the official corpus is not copied", out.get("official_files") == 0, str(out))
    check("F05 the outside secret does not reach the store",
          not (dest / "tv.official" / "secret.txt").exists())
    check("F05 the refusal is recorded for the operator",
          any("symlinked staged" in n for n in out.get("notes") or []), str(out.get("notes")))
    os.symlink(outside, sb / "store" / "tv.manuscripts")
    out2 = pp.publish_add_venue_staging(sb, dest, "tv")
    check("F05 the exemplar tree is refused the same way",
          out2.get("manuscript_files") == 0
          and any("symlinked staged" in n for n in out2.get("notes") or []), str(out2))


# ---------------------------------------------------------------------------
# F07 -- an atomic write refuses a symlinked parent directory
# ---------------------------------------------------------------------------
def test_f07() -> None:
    print("\n== F07: atomic writers refuse a symlinked parent ==")
    base = scratch("f07_")
    outside = base / "outside"
    outside.mkdir()
    victim = outside / "created.json"
    victim.write_text("SAFE", encoding="utf-8")
    sb = base / "sb"
    sb.mkdir()
    os.symlink(outside, sb / "redirect")
    for label, call in (
            ("write_json_atomic",
             lambda: pp.write_json_atomic(sb / "redirect" / "created.json", {"x": 1})),
            ("write_text_atomic",
             lambda: pp.write_text_atomic(sb / "redirect" / "created.txt", "X")),
            ("tmp_path_for", lambda: pp.tmp_path_for(sb / "redirect" / "x"))):
        try:
            call()
            raised = False
        except OSError:
            raised = True
        check(f"F07 {label} refuses the symlinked parent", raised)
    check("F07 the outside file is untouched", victim.read_text(encoding="utf-8") == "SAFE")

    # R01: a link at a NON-immediate ancestor used to redirect the parent
    # mkdir and the replace; the walk must cover the whole parent chain.
    outside2 = base / "outside2"
    outside2.mkdir()
    os.symlink(outside2, sb / "link")
    for label, call in (
            ("write_text_atomic",
             lambda: pp.write_text_atomic(sb / "link" / "sub" / "created.txt", "X")),
            ("write_json_atomic",
             lambda: pp.write_json_atomic(sb / "link" / "sub" / "created.json", {"x": 1})),
            ("tmp_path_for", lambda: pp.tmp_path_for(sb / "link" / "sub" / "x"))):
        try:
            call()
            raised = False
        except OSError:
            raised = True
        check(f"F07 {label} refuses a symlinked grandparent", raised)
    check("F07 nothing was created through the grandparent link",
          not (outside2 / "sub").exists(), str(list(outside2.rglob("*"))))
    # ... and the same when the linked-through directory already exists, so no
    # mkdir takes place at all.
    (outside2 / "existing").mkdir()
    try:
        pp.write_text_atomic(sb / "link" / "existing" / "created2.txt", "X")
        raised = False
    except OSError:
        raised = True
    check("F07 an existing directory behind the link is refused too", raised)
    check("F07 the existing outside directory is untouched",
          not (outside2 / "existing" / "created2.txt").exists())

    # A LEGITIMATE root may itself live under a symlinked ancestor (operator
    # checkout mounted through a link): an anchor registered at/above the link
    # keeps the write working, so the refusal is scoped to links the pipeline
    # traverses BELOW its trusted root.
    real = base / "real_root"
    (real / "reports").mkdir(parents=True)
    alias = base / "alias"
    os.symlink(real, alias)
    pp.register_write_anchor(alias)
    try:
        pp.write_text_atomic(alias / "reports" / "ok.txt", "OK")
        anchored = (real / "reports" / "ok.txt").read_text(encoding="utf-8") == "OK"
    except OSError:
        anchored = False
    check("F07 a registered trusted root above the link stays writable", anchored)


# ---------------------------------------------------------------------------
# F13 -- sync-code preserves the shims' executable bit and repairs it
# ---------------------------------------------------------------------------
def test_f13() -> None:
    print("\n== F13: sync-code preserves/repairs the shell shims' mode ==")
    tmp = scratch("f13_")
    root = setup_root(tmp)
    shim = root / "docx2pdf.sh"
    before = stat.S_IMODE(shim.stat().st_mode)
    os.chmod(shim, 0o644)
    r = run(["sync-code", "--root", str(root)])
    after = stat.S_IMODE(shim.stat().st_mode)
    check("F13 sync-code succeeds", r.returncode == 0, (r.stderr or r.stdout)[-300:])
    check("F13 the executable bit is preserved after a content-identical copy",
          before == 0o755 and after == 0o755, f"before={oct(before)} after={oct(after)}")
    check("F13 a mode-only drift is reported as changed",
          "copied: docx2pdf.sh" in (r.stdout + r.stderr), (r.stdout or "")[-200:])


# ---------------------------------------------------------------------------
# F14 -- path normalization strips only an exact leading ./
# ---------------------------------------------------------------------------
def test_f14() -> None:
    print("\n== F14: path normalization does not eat leading dots/slashes ==")
    norm = pp.strip_leading_dot_slash
    check("F14 '../outside/x' keeps its traversal", norm("../outside/x") == "../outside/x")
    check("F14 '.hidden/x' keeps its leading dot", norm(".hidden/x") == ".hidden/x")
    check("F14 './x' and Windows separators normalize",
          norm(".\\x") == "x" and norm("./x") == "x")
    # The scoped guard reads the ledger: a row naming '../outside/doc.docx'
    # must not authorize a changed 'doc.docx'.
    tmp = scratch("f14_")
    sb = tmp / "r1_a2_revise"
    base, rev = sb / "base", sb / "revised"
    base.mkdir(parents=True)
    rev.mkdir(parents=True)
    (base / "doc.docx").write_text("A", encoding="utf-8")
    (rev / "doc.docx").write_text("B", encoding="utf-8")
    (rev / "revision_report.json").write_text(json.dumps(
        [{"id": "F-001", "verdict": "fixed", "file": "../outside/doc.docx"}]),
        encoding="utf-8")
    errs = pp.scoped_scope_problems(None, sb, rev)
    check("F14 a traversal row does not authorize the real file",
          any("doc.docx" in e for e in errs), str(errs)[:200])


# ---------------------------------------------------------------------------
# F17 -- coverage dispositions reject negations and filler reasons
# ---------------------------------------------------------------------------
def test_f17() -> None:
    print("\n== F17: coverage dispositions are positive and reasoned ==")
    for text in ("never verified at all", "the sweep was not re-derived",
                 "could not be checked"):
        check(f"F17 {text!r} is refused",
              not pp.AUDIT_COVERAGE_DISPOSITION_RE.match(text))
    for text in ("stub: the sweep was re-derived; clean",
                 "confirmed by re-opening every cited artifact",
                 "clean -- basis: artifacts/M1.md", "3 findings"):
        check(f"F17 {text!r} is accepted", bool(pp.AUDIT_COVERAGE_DISPOSITION_RE.match(text)))
    audit = {"coverage": [{"check": c, "disposition": "never verified at all"}
                          for c in pp.AUDIT_COVERAGE_CHECKS]}
    check("F17 filling every audit row with a negation fails the gate",
          bool(pp.audit_coverage_problems(audit)), str(pp.audit_coverage_problems(audit))[:160])
    check("F17 'unable -- no' is filler", not pp._coverage_disposition_ok("unable -- no"))
    check("F17 'unable -- no PDF renderer' names a reason",
          pp._coverage_disposition_ok("unable -- no PDF renderer"))
    check("F17 the audit gate also rejects filler reasons",
          not pp._audit_disposition_ok("unable -- no")
          and not pp._audit_disposition_ok("clean -- basis: x")
          and pp._audit_disposition_ok("unable -- no PDF renderer"))
    # R02: a bare `out of scope` was the remaining filler shape: the regex
    # accepted it and the reason check was never reached, so all 41 audit rows
    # could carry it.
    for text in ("out of scope", "out of scope --", "out of scope -- .",
                 "out of scope -- no"):
        check(f"F17 bare {text!r} is refused by both gates",
              not pp._coverage_disposition_ok(text)
              and not pp._audit_disposition_ok(text))
    check("F17 'out of scope -- formatting-only pass' names a reason",
          pp._coverage_disposition_ok("out of scope -- formatting-only pass")
          and pp._audit_disposition_ok("out of scope -- formatting-only pass"))
    audit_scope = {"coverage": [{"check": c, "disposition": "out of scope"}
                                for c in pp.AUDIT_COVERAGE_CHECKS]}
    scope_problems = pp.audit_coverage_problems(audit_scope)
    check("F17 filling every audit row with bare out-of-scope fails the gate",
          len(scope_problems) == len(pp.AUDIT_COVERAGE_CHECKS), str(scope_problems)[:160])


# ---------------------------------------------------------------------------
# F18 -- donor coverage compares ids exactly, not by substring
# ---------------------------------------------------------------------------
def test_f18() -> None:
    print("\n== F18: integration donor coverage is exact ==")
    d = scratch("f18_")
    (d / "DIFF_LEDGER.md").write_text(
        "| id | donor | location | size | donor says | self says | verdict | revalidated | why "
        "| effect | artifact | finding effect |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| R-001 | w10 | x | small | a | b | keep-self | rejected | x | none "
        "| work/diffs/a | none |\n", encoding="utf-8")
    report = pp.integration_ledger_report(d, ["w1", "w10"], False)
    check("F18 a missing w1 is reported next to w10", report["donors_absent"] == ["w1"],
          str(report["donors_absent"]))


# ---------------------------------------------------------------------------
# F20 -- setup/agents do not print sessions a no-judge mode never runs
# ---------------------------------------------------------------------------
def test_f20() -> None:
    print("\n== F20: no-judge modes print no judge/integration sessions ==")
    tmp = scratch("f20_")
    src = make_source(tmp)
    root = tmp / "revise_root"
    r = run(["setup", "--source", str(src), "--root", str(root), "--rounds", "1",
             "--champion-select", "revise"])
    out = r.stdout + r.stderr
    check("F20 revise setup succeeds", r.returncode == 0, out[-300:])
    check("F20 revise prints no integration arm",
          "NO integration arm" in out and "i1 =" not in out, out[-500:])
    check("F20 revise prints no expected judge sessions",
          "expected judge sessions" not in out and "judge sessions:         none" in out,
          out[-400:])
    a = run(["agents", "--root", str(root), "--json"])
    data = json.loads(a.stdout[a.stdout.index("{"):]) if a.returncode == 0 else {}
    check("F20 revise agents lists zero judge sessions",
          a.returncode == 0 and sum(len(x["judge"]) for x in data["rounds"]) == 0,
          (a.stdout or a.stderr)[-300:])
    check("F20 revise agents lists zero integrators",
          all(x["integrators"] == "0x0" for x in data.get("rounds") or []))

    root2 = tmp / "integrate_root"
    r2 = run(["setup", "--source", str(src), "--root", str(root2), "--rounds", "1",
              "--rewrites", "0", "--revises", "1", "--integrators", "3",
              "--champion-select", "integrate"])
    out2 = r2.stdout + r2.stderr
    check("F20 integrate setup succeeds", r2.returncode == 0, out2[-300:])
    check("F20 integrate keeps its integration arms", "i1 = a1" in out2 and "i2 = a2" in out2,
          out2[-400:])
    check("F20 integrate prints no judge panel", "judges per round:       none" in out2,
          out2[-400:])


# ---------------------------------------------------------------------------
# F21 -- a scoped setup saves the operator's review_scope before truncating it
# ---------------------------------------------------------------------------
def test_f21() -> None:
    print("\n== F21: scoped setup restores the operator's review scope ==")
    tmp = scratch("f21_")
    src = make_source(tmp)
    root = tmp / "root"
    r = run(["setup", "--source", str(src), "--root", str(root),
             "--revision-mode", "major",
             "--review-scope", "full,full,formatting-writing"])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    saved = (cfg.get("scoped_mode_restore") or {}).get("review_scope")
    check("F21 setup succeeds", r.returncode == 0, (r.stderr or r.stdout)[-300:])
    check("F21 the saved plan carries all three requested scopes",
          saved == ["full", "full", "formatting-writing"], str(saved))
    r2 = run(["set-revision-mode", "continue", "--force", "--root", str(root)])
    cfg2 = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("F21 leaving the mode succeeds", r2.returncode == 0,
          (r2.stderr or r2.stdout)[-300:])
    check("F21 leaving the mode restores the three-round scope",
          cfg2.get("review_scope") == ["full", "full", "formatting-writing"],
          str(cfg2.get("review_scope")))


# ---------------------------------------------------------------------------
# F23 -- decide with no completed round still writes the promised readme
# ---------------------------------------------------------------------------
def test_f23() -> None:
    print("\n== F23: decide writes the status readme when no round completed ==")
    tmp = scratch("f23_")
    root = setup_root(tmp)
    r = run(["decide", "--root", str(root)])
    readme = root / "final_clean_version.readme.md"
    check("F23 decide still exits 2", r.returncode == 2, str(r.returncode))
    check("F23 the sibling readme exists", readme.is_file())
    text = readme.read_text(encoding="utf-8") if readme.is_file() else ""
    check("F23 the readme says NOT CERTIFIED and names the no-round state",
          "NOT CERTIFIED" in text and "no completed round" in text, text[:240])


# ---------------------------------------------------------------------------
# F24 -- prune --keep-latest 0 prints a possible retention message
# ---------------------------------------------------------------------------
def test_f24() -> None:
    print("\n== F24: prune --keep-latest 0 does not print an impossible range ==")
    tmp = scratch("f24_")
    root = setup_root(tmp, "--rounds", "3")
    r = run(["prune", "--root", str(root), "--keep-latest", "0"])
    out = r.stdout + r.stderr
    check("F24 prune succeeds", r.returncode == 0, out[-300:])
    check("F24 no 'rounds 4..3' range is printed", "4..3" not in out, out[-300:])
    check("F24 the message says no completed round is kept",
          "NO completed round's sandbox" in out, out[-300:])


# ---------------------------------------------------------------------------
# F25 -- a JSON-list config is a clean refusal, never an AttributeError
# ---------------------------------------------------------------------------
def test_f25() -> None:
    print("\n== F25: a non-object pipeline_config.json fails cleanly ==")
    tmp = scratch("f25_")
    root = setup_root(tmp)
    (root / "pipeline_config.json").write_text("[]", encoding="utf-8")
    r = run(["status", "--root", str(root)])
    out = r.stdout + r.stderr
    check("F25 status exits non-zero", r.returncode != 0, str(r.returncode))
    check("F25 the refusal names the non-object config",
          "does not carry a JSON object" in out, out[-300:])
    check("F25 there is no traceback", "Traceback (most recent call last)" not in out, out[-300:])


# ---------------------------------------------------------------------------
# F26 -- every usage/validation error exits 2
# ---------------------------------------------------------------------------
def test_f26() -> None:
    print("\n== F26: usage errors exit 2 ==")
    tmp = scratch("f26_")
    src = make_source(tmp)
    for label, args in (
            ("--judges -1", ["--judges", "-1"]),
            ("--rewrites -1", ["--rewrites", "-1"]),
            ("--integrators overflow", ["--integrators", "0x100000000"])):
        root = tmp / ("root_" + re.sub(r"\W+", "_", label))
        r = run(["setup", "--source", str(src), "--root", str(root), *args])
        check(f"F26 setup {label} exits 2", r.returncode == 2, str(r.returncode))
    root = tmp / "run_root"
    r0 = run(["setup", "--source", str(src), "--root", str(root), "--rounds", "2",
              "--judges", "1"])
    check("F26 the run fixture sets up", r0.returncode == 0, (r0.stderr or r0.stdout)[-200:])
    for label, args in (("run --timeout -1", ["--timeout", "-1"]),
                        ("run --only 1-65", ["--only", "1-65"])):
        r = run(["run", "--root", str(root), *args])
        check(f"F26 {label} exits 2", r.returncode == 2, str(r.returncode))


# ---------------------------------------------------------------------------
# F30/F31 -- policy null and non-finite venue numbers
# ---------------------------------------------------------------------------
def test_f30_f31() -> None:
    print("\n== F30/F31: null policy means default; non-finite profile numbers refused ==")
    check("F30 an explicit null means the default in the pipeline scanner",
          pp._policy_flag({"figure_ocr": None}, "figure_ocr", True) is True)
    check("F30 the formatter agrees",
          fmt._policy_flag({"figure_ocr": None}, "figure_ocr", True) is True)
    base = {"id": "t", "label": "T",
            "article_types": [{"id": "article", "label": "Article",
                               "length_limits": {
                                   "abstract": {"base": 150, "relaxation": float("nan")},
                                   "main_text": {"base": 3000, "relaxation": 1.25}}}]}
    try:
        pp.VenueProfile(base, origin="test")
        refused_nan = False
    except (ValueError, pp.VenueProfileError):
        refused_nan = True
    check("F31 NaN relaxation is refused at load", refused_nan)
    base["article_types"][0]["length_limits"]["abstract"]["relaxation"] = float("inf")
    try:
        pp.VenueProfile(base, origin="test")
        refused_inf = False
    except (ValueError, pp.VenueProfileError):
        refused_inf = True
    check("F31 Infinity relaxation is refused at load", refused_inf)
    base["article_types"][0]["length_limits"]["abstract"]["relaxation"] = 1.1
    base["image_dpi"] = {"min_dpi": float("inf"), "source": "x"}
    try:
        pp.VenueProfile(base, origin="test")
        refused_dpi = False
    except (ValueError, pp.VenueProfileError):
        refused_dpi = True
    check("F31 Infinity image_dpi floor is refused at load", refused_dpi)


# ---------------------------------------------------------------------------
# F36-F39 -- documentation names the shipped ids/paths/vocabulary
# ---------------------------------------------------------------------------
def test_docs() -> None:
    print("\n== F36-F39: documentation matches the shipped names ==")
    readme = (WS / "README.md").read_text(encoding="utf-8")
    check("F36 README names the printed guided-review ids",
          "r1_guided_review" in readme and "r1_guided_review_b" in readme
          and "`review_b`" not in readme)
    check("F37 README names the shipped count_words.py path",
          "paper-skills/paper-review/scripts/count_words.py" in readme
          and "`scripts/count_words.py`" not in readme)
    check("F37 .paper_test README names the shipped path too",
          "paper-skills/paper-review/scripts/count_words.py" in
          (HERE / "README.md").read_text(encoding="utf-8"))
    venue_readme = (WS / "venue_profiles" / "README.md").read_text(encoding="utf-8")
    line = next((ln for ln in venue_readme.splitlines()
                 if ln.startswith("| `counting.main_text.excludes`")), "")
    check("F38 the counting vocabulary documents table-contents",
          "`table-contents`" in line, line[:200])
    sync_doc = (WS / "paper_pipeline_parts" / "p12_conflicts_decide.py").read_text(
        encoding="utf-8")
    body = sync_doc[sync_doc.index("def cmd_sync_code"):]
    body = body[:body.index("\n    root = Path")]
    for name in ("paper_pipeline.py", "paper_docx_format.py", "paper_redlines_adapter.py",
                 "paper_qwen_agent.py", "docx2pdf.sh", "docxcompare.sh"):
        check(f"F39 sync-code docstring names {name}", f"`{name}`" in body)


# ---------------------------------------------------------------------------
# F53/F54 -- the shipped probe and validator are green
# ---------------------------------------------------------------------------
def test_shipped_probe_and_validator() -> None:
    print("\n== F53/F54: the shipped probe R10 and the C20 validator pass ==")
    tmp = scratch("probes_")
    probe = subprocess.run(
        [sys.executable, str(WS / "paper-skills/tests/probe_regressions.py"),
         "--skill-root", str(WS / "paper-skills"), "--run-dir", str(tmp / "probe")],
        capture_output=True, text=True, timeout=1200)
    check("F53 every shipped regression probe passes (incl. R10)",
          probe.returncode == 0 and "PASS R10" in probe.stdout,
          (probe.stdout or probe.stderr)[-400:])
    val = subprocess.run(
        [sys.executable, str(WS / "paper-skills/tests/validate_skill.py"),
         "--skill-root", str(WS / "paper-skills"), "--run-dir", str(tmp / "validate")],
        capture_output=True, text=True, timeout=1200)
    check("F54 validate_skill reports 52/52 (C20 included)",
          val.returncode == 0 and "52 checks, 0 failed" in val.stdout,
          (val.stdout or val.stderr)[-400:])


# ---------------------------------------------------------------------------
# F73 -- the MCP child runner rejects over-budget output instead of truncating
# ---------------------------------------------------------------------------
def test_f73() -> None:
    print("\n== F73: over-budget child output is an error ==")
    node = shutil.which("node")
    if not node:
        check("F73 node is available for the check", True, "skipped: node not installed")
        return
    tmp = scratch("f73_")
    # R03: the two MCP servers ship byte-identical child runners; the
    # over-budget contract must hold in BOTH, not only in the converter copy.
    for server in ("mcp-docx-converter", "mcp-docx-compare"):
        script = tmp / f"check_{server.replace('-', '_')}.mjs"
        runner = (WS / server / "run-child.mjs").as_uri()
        script.write_text(f"""
import {{ runFile }} from {runner!r};
try {{
  await runFile(process.execPath, ['-e', "process.stdout.write('x'.repeat(100000))"],
                {{ maxBuffer: 100 }});
  console.log('RESOLVED');
  process.exit(1);
}} catch (e) {{
  if (!e.overBudget || !e.killed) {{ console.log('BAD', e.message); process.exit(2); }}
}}
const ok = await runFile(process.execPath, ['-e', "process.stdout.write('hello')"],
                         {{ maxBuffer: 100 }});
if (ok.stdout !== 'hello') {{ console.log('BAD-NORMAL'); process.exit(3); }}
console.log('OK');
""", encoding="utf-8")
        r = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=120)
        check(f"F73 {server}: over-budget child is rejected and a normal child resolves",
              r.returncode == 0 and "OK" in r.stdout, (r.stdout + r.stderr)[-300:])


# ---------------------------------------------------------------------------
# F76 -- the hidden add-venue scratch tree is never frozen into a root
# ---------------------------------------------------------------------------
def test_f76() -> None:
    print("\n== F76: venue_profiles/.add-venue is not frozen into a root ==")
    tmp = scratch("f76_")
    root = setup_root(tmp)
    check("F76 a fresh root carries no .add-venue scratch",
          not (root / "venue_profiles" / ".add-venue").exists())
    src = tmp / "copy_src" / "venue_profiles"
    (src / ".add-venue" / "run1").mkdir(parents=True)
    (src / ".add-venue" / "run1" / "_agent.log").write_text("private", encoding="utf-8")
    (src / "ok.json").write_text("{}", encoding="utf-8")
    dst = tmp / "copy_dst"
    pp.copy_asset_dirs(tmp / "copy_src", dst, names=("venue_profiles",))
    check("F76 copy_asset_dirs skips the scratch tree",
          not (dst / "venue_profiles" / ".add-venue").exists()
          and (dst / "venue_profiles" / "ok.json").is_file())
    digest_with = pp.asset_dir_digest(tmp / "copy_src", "venue_profiles")
    (src / ".add-venue" / "run1" / "more.log").write_text("more", encoding="utf-8")
    check("F76 the asset digest ignores scratch too",
          pp.asset_dir_digest(tmp / "copy_src", "venue_profiles") == digest_with)


# ---------------------------------------------------------------------------
# F79 -- a failed final-clean archive blocks certification
# ---------------------------------------------------------------------------
def test_f79() -> None:
    print("\n== F79: a failed final-clean ZIP is a certification blocker ==")
    check("F79 a successful archive adds no blocker",
          pp.final_clean_publication_problems({"zip": {"ok": True, "path": "x"}}) == [])
    blockers = pp.final_clean_publication_problems(
        {"zip": {"ok": False, "error": "disk full"}})
    check("F79 a failed archive is a blocker",
          any("archive was not written" in b and "disk full" in b for b in blockers),
          str(blockers))
    # End to end: a directory planted at the archive's path makes the ZIP fail;
    # `decide` must not sign the package.
    tmp = scratch("f79_")
    src = make_source(tmp)
    root = tmp / "root"
    setup = run(["setup", "--source", str(src), "--root", str(root), "--rounds", "1",
                 "--judges", "1", "--rewrites", "0", "--revises", "1",
                 "--integrators", "1"])
    check("F79 the stub fixture sets up", setup.returncode == 0,
          (setup.stderr or setup.stdout)[-200:])
    stub = HERE / "stub_agent.py"
    ran = run(["run", "--root", str(root), "--agent-cmd",
               json.dumps([sys.executable, str(stub)]), "--retries", "0"])
    check("F79 the stub round completes", ran.returncode == 0,
          (ran.stderr or ran.stdout)[-300:])
    (root / (pp.final_clean_dirname(root) + ".zip")).mkdir()
    dec = run(["decide", "--root", str(root)])
    decision = json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))
    cert = decision.get("certification") or {}
    check("F79 decide exits 5 (not certified)", dec.returncode == 5, str(dec.returncode))
    check("F79 certification is not signed", cert.get("certified") is False,
          str(cert.get("certified")))
    check("F79 the archive failure is a named blocker",
          any("archive was not written" in str(b) for b in cert.get("blockers") or []),
          str(cert.get("blockers"))[-300:])


def cleanup() -> None:
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_f05()
        test_f07()
        test_f13()
        test_f14()
        test_f17()
        test_f18()
        test_f20()
        test_f21()
        test_f23()
        test_f24()
        test_f25()
        test_f26()
        test_f30_f31()
        test_docs()
        test_shipped_probe_and_validator()
        test_f73()
        test_f76()
        test_f79()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-10-31 18:00 FIX-BUGS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

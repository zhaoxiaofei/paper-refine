#!/usr/bin/env python3
"""Regression checks for the confirmed findings of the 2026-09-19 bug audit.

Run:  python3 .nbt_test/test_bug_audit_2026_0919.py

Every check names the candidate id from the audit reports under
`nbt_audit_data/2026-0919-1336-potential-bug-report/`. Only *confirmed* defects
are asserted here; unfixed candidates are listed in that audit's final report.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xfix as xf  # noqa: E402

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_audit", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_audit"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def run_py(script: Path, *args, env=None):
    return subprocess.run([sys.executable, str(script)] + [str(a) for a in args],
                          capture_output=True, text=True, env=env, timeout=300)


def main_text_rows(tmp: Path, name: str) -> list:
    info = nb.scan_lengths_in_sources([(tmp, "", ())])
    return [r for r in info["rows"] if r["document"].endswith(name)
            and r["section"] == "main text"]


# =====================================================================
# C01 -- Python 3.9-3.11 syntax (the docstring advertises 3.9+)
# =====================================================================

def test_c01_python310_parse():
    py = "/usr/bin/python3.10"
    if not os.path.exists(py):
        print("[skip] C01 no /usr/bin/python3.10 available")
        return
    proc = subprocess.run(
        [py, "-c", "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read())",
         str(WS / "nbt_pipeline.py")], capture_output=True, text=True)
    check("C01 nbt_pipeline.py parses on Python 3.10", proc.returncode == 0,
          (proc.stderr or proc.stdout)[-160:])


# =====================================================================
# C02 -- the visual gate must use the MCP-aware probe
# =====================================================================

def test_c02_visual_gate():
    probes, configured = nb.VISUAL_TOOL_PROBES, nb.mcp_server_configured
    try:
        nb.VISUAL_TOOL_PROBES = (("MCP converter", "mcp:docx-converter"),)
        nb.mcp_server_configured = lambda name: True
        check("C02 an MCP-only renderer counts as available", nb.visual_tools_available() is True)
        nb.mcp_server_configured = lambda name: False
        check("C02 an unconfigured MCP renderer is not available",
              nb.visual_tools_available() is False)
    finally:
        nb.VISUAL_TOOL_PROBES, nb.mcp_server_configured = probes, configured


# =====================================================================
# C03 -- M19 main-text end must be a heading, not any prose line
# =====================================================================

def test_c03_length_anchoring():
    tmp = scratch("nbt_audit_len_")
    body = "Abstract\n\n" + ("w " * 50) + "\n\nIntroduction\n\n" + ("t " * 200)
    prose_line = ("Methods for isolating T cells followed a published protocol in full "
                  "detail.")
    write(tmp / "plain.md", body + "\n\nMethods\n\nx\n")
    write(tmp / "prose.md", body + "\n" + prose_line + "\n\nMethods\n\nx\n")
    write(tmp / "star.md", body + "\n\nSTAR Methods\n\n" + ("m " * 80) + "\n\nReferences\n\nx\n")
    want_prose = 200 + nb.count_words(prose_line)
    plain = main_text_rows(tmp, "plain.md")
    prose = main_text_rows(tmp, "prose.md")
    star = main_text_rows(tmp, "star.md")
    check("C03 a prose line starting 'Methods ...' does not truncate the count",
          plain and prose and prose[0]["words"] == want_prose,
          f"plain={plain[0]['words'] if plain else None} prose={prose[0]['words'] if prose else None}")
    check("C03 'STAR Methods' ends the main text", star and star[0]["words"] == 200,
          str(star))
    for name, want in (("plain.md", 200), ("prose.md", want_prose), ("star.md", 200)):
        proc = run_py(WS / "nbt-skills/nbt-review/scripts/count_words.py", tmp / name,
                      "--section", "main-text", "--json")
        rows = [r for r in json.loads(proc.stdout)["rows"] if r["section"] == "main text"]
        check(f"C03 count_words.py agrees on {name}", rows and rows[0]["words"] == want,
              f"{rows[0]['words'] if rows else None} != {want}")


# =====================================================================
# C04 -- a cover letter opening with a date block must be detected
# =====================================================================

def test_c04_cover_letter():
    tmp = scratch("nbt_audit_cover_")
    write(tmp / "letter.md",
          "September 19, 2026\n\nDr. Editor\nNature Biotechnology\n\nDear Editor,\n\n"
          + ("persuade " * 400).strip() + "\n\nSincerely,\nJane Doe\n")
    rows = [r for r in nb.scan_lengths_in_sources([(tmp, "", ())])["rows"]
            if r["section"] == "cover letter"]
    check("C04 the date-first cover letter gets an M19 row",
          rows and rows[0]["words"] == 400 and rows[0]["within_preference"] is True,
          str(rows[:1]))
    proc = run_py(WS / "nbt-skills/nbt-review/scripts/count_words.py", tmp / "letter.md",
                  "--section", "cover-letter", "--json")
    crows = [r for r in json.loads(proc.stdout)["rows"] if r["section"] == "cover letter"]
    check("C04 count_words.py detects it too", crows and crows[0]["words"] == 400,
          str(crows[:1]))


# =====================================================================
# C05/C06 -- revision-token warning + rename-stable normalization
# =====================================================================

def test_c05_c06_revision_token():
    legacy = scratch("nbt_audit_legacy_")
    write(legacy / "ms-a.tex", "panel-a discussed in the text\n")
    rec, warns = {}, []
    nb._record_revision_token(rec, legacy, warns)
    check("C05 a legacy letter token does NOT produce a mismatch warning",
          warns == [] and rec["revision_token"]["tokens_seen"] == ["a"],
          str(warns))
    tok = nb.revision_token_for_dir(legacy)["token"]
    (legacy / "ms-a.tex").rename(legacy / f"ms-{tok}.tex")
    check("C06 the token is stable when applied (prose '-a' untouched)",
          nb.revision_token_for_dir(legacy)["token"] == tok)
    refs = scratch("nbt_audit_refs_")
    write(refs / "ms-a.tex", "\\addbibresource{refs-a.bib}\n")
    write(refs / "refs-a.bib", "@article{x}\n")
    t1 = nb.revision_token_for_dir(refs)["token"]
    (refs / "ms-a.tex").rename(refs / f"ms-{t1}.tex")
    (refs / "refs-a.bib").rename(refs / f"refs-{t1}.bib")
    write(refs / f"ms-{t1}.tex", f"\\addbibresource{{refs-{t1}.bib}}\n")
    check("C06 a repointed reference keeps the token stable",
          nb.revision_token_for_dir(refs)["token"] == t1)
    v2 = scratch("nbt_audit_v2_")
    write(v2 / "report-V2.tex", "x\n")
    check("C06 the pipeline recognizes an uppercase V-style token",
          nb.revision_token_for_dir(v2)["tokens_seen"] == ["V2"])
    spec2 = importlib.util.spec_from_file_location(
        "rt", str(WS / "nbt-skills/nbt-revise/scripts/revision_token.py"))
    rt = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(rt)
    check("C06 the vendored tool agrees on the uppercase V-style token",
          rt.filename_token("report-V2.tex") == "V2")


# =====================================================================
# C07 -- an all-clean review makes an empty ledger legitimate
# =====================================================================

def test_c07_empty_ledger():
    tmp = scratch("nbt_audit_ledger_")
    root = tmp / "root"
    pristine = root / "non-revised"
    write(pristine / "manuscript-b.md", "text\n")
    (root / "reports").mkdir(parents=True)
    ctx = nb.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": 1, "caption_limit": 0}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": nb.hash_manifest(pristine),
                 "original_digest": "x", "judge_salt": "s", "config": ctx.cfg}
    rid = "r1_a2_revise"
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True)
    shutil.copytree(pristine, sb / "base")
    shutil.copytree(pristine, sb / "non-revised")
    write(sb / "review" / "findings.json",
          json.dumps({"submission_dir": "./base", "findings": [], "artifacts": {},
                      "coverage": []}))
    rev = sb / "revised"
    shutil.copytree(pristine, rev)
    xf.write_language_pass(rev)
    write(rev / "revision_report.json", "[]")
    write(rev / "CHANGELOG.md", "# changelog\n")
    write(rev / "MANUAL_STEPS.md", "1. (none)\n")
    write(rev / "VISUAL_CHECK.md", "not visually verified\n")
    write(sb / "_pipeline_done.json", json.dumps(
        {"stage": "revise", "run_id": rid, "round": 1, "status": "complete",
         "summary": {"findings_total": 0, "fixed": 0, "critical_remaining": 0,
                     "manual_items": 0}}))
    rec = ctx.register(rid, "revise", 1, f"runs/{rid}", upstream_run_id="r1_a2_review",
                       source_id="a1")
    rec["inputs_manifest"] = {"base": nb.hash_manifest(sb / "base"),
                              "non-revised": nb.hash_manifest(sb / "non-revised"),
                              "review": nb.hash_manifest(sb / "review")}
    ok, errs, warns, _extra = (list(nb.postcheck_revise(ctx, rec)) + [None])[:4]
    check("C07 a zero-finding review with an empty ledger is accepted",
          ok is True and not any("EMPTY/unfinished" in e for e in errs),
          f"ok={ok} errs={errs[:1]}")
    check("C07 ... and reported as an all-clean ledger",
          any("all-clean" in w for w in warns), str(warns[:2]))


# =====================================================================
# C08 -- final_clean counter renames: collisions and transient occupancy
# =====================================================================

def test_c08_counter_renames():
    normal = scratch("nbt_audit_counter_")
    write(normal / "cnb-11-x.txt", "A\n")
    write(normal / "cnb-12-x.txt", "B\n")
    info = nb._increment_final_clean_counters(normal)
    check("C08 transient occupancy is renamed loss-free",
          info["renamed"] == 2 and not info["collisions"]
          and (normal / "cnb-12-x.txt").read_text() == "A\n"
          and (normal / "cnb-13-x.txt").read_text() == "B\n",
          str(sorted(p.name for p in normal.iterdir())))
    clash = scratch("nbt_audit_clash_")
    write(clash / "cnb-011-x.txt", "A\n")
    write(clash / "cnb-11-x.txt", "B\n")
    cinfo = nb._increment_final_clean_counters(clash)
    check("C08 a genuine target collision is reported, not overwritten",
          cinfo["renamed"] == 0 and len(cinfo["collisions"]) == 1
          and sorted(p.name for p in clash.iterdir()) == ["cnb-011-x.txt", "cnb-11-x.txt"],
          str(cinfo))


# =====================================================================
# C09 -- the vendored token tool must fail on a missing directory
# =====================================================================

def test_c09_token_tool_missing_dir():
    proc = run_py(WS / "nbt-skills/nbt-revise/scripts/revision_token.py",
                  "/tmp/nbt-audit-does-not-exist-xyz")
    check("C09 a nonexistent directory exits non-zero", proc.returncode != 0
          and "not a directory" in (proc.stderr + proc.stdout), f"rc={proc.returncode}")


# =====================================================================
# C10 -- raw_scores.csv must resolve the label like the aggregator
# =====================================================================

def test_c10_raw_scores_label():
    tmp = scratch("nbt_audit_raw_")
    rec = {"id": "r1_judge_t_x_j1", "kind": "judge", "round": 1, "judge_index": 1,
           "target_id": "a1", "label_map": {"v1": "w1"},
           "scores": {"comparisons": [{"opponent_label": "V1", "score": 1}]}}

    class FakeCtx:
        reports_dir = tmp

        @staticmethod
        def runs(kind=None, round_no=None):
            return [rec]

    path = nb.write_raw_scores(FakeCtx(), [{"round": 1}])
    import csv as _csv
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    check("C10 a case-slipped judge label still maps to its version id",
          rows and rows[0]["opponent_id"] == "w1" and rows[0]["opponent_label"] == "V1",
          str(rows))


# =====================================================================
# C12 -- uncited references are computed per document
# =====================================================================

def test_c12_citations_uncited():
    work = scratch("nbt_audit_cit_")
    write(work / "corpus" / "manuscript.txt",
          "We measured [1] and [2].\n\nReferences\n\n1. A\n2. B\n3. C\n")
    write(work / "corpus" / "cover_letter.txt", "See [3] for context.\n")
    out = work / "out"
    proc = run_py(WS / "nbt-skills/nbt-review/scripts/extract_citations.py",
                  "--work", work, "--out", out)
    artifact = ""
    for p in sorted(out.rglob("*")):
        if p.is_file() and "citation" in p.name.lower():
            artifact += p.read_text(encoding="utf-8", errors="replace")
    check("C12 the manuscript's uncited [3] is not masked by the cover letter",
          "[3]" in artifact and "manuscript" in artifact.lower(),
          f"rc={proc.returncode} artifact={artifact[:120]!r}")


# =====================================================================
# C13 -- RTF non-BMP escapes must not crash the corpus write
# =====================================================================

def test_c13_rtf_surrogates():
    cc_spec = importlib.util.spec_from_file_location(
        "cc", str(WS / "nbt-skills/nbt-review/scripts/convert_corpus.py"))
    cc = importlib.util.module_from_spec(cc_spec)
    cc_spec.loader.exec_module(cc)
    tmp = scratch("nbt_audit_rtf_")
    (tmp / "note.rtf").write_bytes(b"{\\rtf1\\ansi Test \\u-10179?\\u-8700? done}")
    text, notes = cc.rtf_to_text(str(tmp / "note.rtf"))
    try:
        text.encode("utf-8")
        ok = True
    except UnicodeEncodeError:
        ok = False
    check("C13 a surrogate-pair escape converts and encodes", ok and "\U0001F604" in text,
          repr(text))


# =====================================================================
# C14 -- roman-numeral look-alikes and the extra-tokens escape hatch
# =====================================================================

def test_c14_roman_lookalikes():
    work = scratch("nbt_audit_acr_")
    write(work / "corpus" / "ms.txt",
          "Patients with CLL had CV of 0.42; tools run from the CLI; CCL2 and CXCL12 measured.\n")
    write(work / "extra_acronyms.txt", "CLL\nCV\nCLI\n")
    out = work / "out"
    run_py(WS / "nbt-skills/nbt-review/scripts/extract_acronyms.py", "--work", work, "--out", out)
    artifact = ""
    for p in sorted(out.rglob("*")):
        if p.is_file() and "M1" in p.name:
            artifact += p.read_text(encoding="utf-8", errors="replace")
    missing = [t for t in ("CLL", "CV", "CLI") if t not in artifact]
    check("C14 CLL/CV/CLI are listed (never silently dropped)", not missing, str(missing))


# =====================================================================
# C15 -- role heuristics must not match substrings
# =====================================================================

def test_c15_guess_role():
    cc_spec = importlib.util.spec_from_file_location(
        "ccr", str(WS / "nbt-skills/nbt-review/scripts/convert_corpus.py"))
    cc = importlib.util.module_from_spec(cc_spec)
    cc_spec.loader.exec_module(cc)
    cases = {"preface.txt": "other", "config.tex": "other", "refresh_notes.md": "other",
             "patient_symptoms.csv": "data", "manuscript.txt": "main text",
             "refs.bib": "references", "fig1.png": "figure"}
    bad = {n: cc.guess_role(n) for n, want in cases.items() if cc.guess_role(n) != want}
    check("C15 role heuristics are word/extension-anchored", not bad,
          str({k: (v, cases[k]) for k, v in bad.items()}))


# =====================================================================
# C17 -- redlines adapter: no traceback from a property getter; main argv[0]
# =====================================================================

def test_c17_redlines_adapter():
    fake = scratch("nbt_audit_redlines_")
    write(fake / "redlines.py",
          "class Redlines:\n"
          "    def __init__(self, base, revised):\n        pass\n"
          "    @property\n"
          "    def output(self):\n        raise RuntimeError('boom')\n")
    base, revised, out = fake / "b.docx", fake / "r.docx", fake / "o.docx"
    base.write_bytes(b"b"); revised.write_bytes(b"r")
    env = dict(os.environ, PYTHONPATH=str(fake))
    proc = run_py(WS / "nbt_redlines_adapter.py", base, revised, out, env=env)
    check("C17 a raising property getter is a clean exit, not a traceback",
          proc.returncode == 5 and "Traceback" not in proc.stderr
          and "no supported docx redline interface" in proc.stderr,
          f"rc={proc.returncode} err={proc.stderr[-140:]!r}")
    fake2 = scratch("nbt_audit_redlines2_")
    write(fake2 / "redlines.py",
          "import sys\n"
          "def main(argv):\n"
          "    if len(argv) == 4 and argv[0] == 'redlines':\n"
          "        open(argv[3], 'wb').write(b'ok')\n"
          "    else:\n        raise SystemExit(2)\n")
    out2 = fake2 / "o.docx"
    env2 = dict(os.environ, PYTHONPATH=str(fake2))
    proc2 = run_py(WS / "nbt_redlines_adapter.py", base, revised, out2, env=env2)
    check("C17 a CLI-shaped redlines.main receives argv[0]",
          proc2.returncode == 0 and out2.read_bytes() == b"ok",
          f"rc={proc2.returncode} err={proc2.stderr[-140:]!r}")


# =====================================================================
# C16 -- docx2pdf.sh: symlinked input and non-ASCII names under LC_ALL=C
# =====================================================================

def test_c16_docx2pdf_paths():
    tmp = scratch("nbt_audit_pdf_")
    (tmp / "real").mkdir()
    (tmp / "link").mkdir()
    (tmp / "bin").mkdir()
    (tmp / "real" / "realfile.docx").write_bytes(b"x")
    os.symlink("../real/realfile.docx", tmp / "link" / "alias.docx")
    fake = tmp / "bin" / "powershell.exe"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(fake, 0o755)
    env = dict(os.environ, PATH=f"{tmp / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}")
    proc = subprocess.run(["bash", str(WS / "docx2pdf.sh"), str(tmp / "link" / "alias.docx")],
                          capture_output=True, text=True, env=env, timeout=120)
    check("C16 a symlinked input resolves to the REAL sibling PDF",
          proc.returncode == 1 and f"{tmp}/real/realfile.pdf" in proc.stderr
          and f"{tmp}/link/alias.pdf" not in proc.stderr,
          proc.stderr[-160:])
    (tmp / "\u8bba\u6587-final.docx").write_bytes(b"y")
    env_c = dict(env, LC_ALL="C")
    proc2 = subprocess.run(["bash", str(WS / "docx2pdf.sh"), str(tmp / "\u8bba\u6587-final.docx")],
                           capture_output=True, text=True, env=env_c, timeout=120)
    check("C16 a non-ASCII name under LC_ALL=C fails on the missing PDF, not on iconv",
          proc2.returncode == 1 and "iconv" not in proc2.stderr
          and "\u8bba\u6587-final.pdf" in proc2.stderr,
          proc2.stderr[-160:])


# =====================================================================
# C18 -- the two M19 caption subtractions must agree (supp legends, wraps)
# =====================================================================

def test_c18_caption_subtraction():
    tmp = scratch("nbt_audit_cap_")
    text = ("Abstract\n\n" + ("w " * 60) + "\n\nIntroduction\n\n" + ("t " * 60)
            + "\n\nFigure 1 | A caption that wraps onto\n"
              "a second line with more words here.\n"
              "Supplementary Figure 1 | A supplementary legend with its own words.\n"
              "\nMethods\n\nx\n")
    write(tmp / "ms.md", text)
    pipe = [r for r in nb.scan_lengths_in_sources([(tmp, "", ())])["rows"]
            if r["section"] == "main text"]
    proc = run_py(WS / "nbt-skills/nbt-review/scripts/count_words.py", tmp / "ms.md",
                  "--section", "main-text", "--json")
    skill = [r for r in json.loads(proc.stdout)["rows"] if r["section"] == "main text"]
    check("C18 the skill and the pipeline subtract the same caption words (body = 60)",
          pipe and skill and pipe[0]["words"] == skill[0]["words"] == 60,
          f"pipeline={pipe[0]['words'] if pipe else None} skill={skill[0]['words'] if skill else None}")


# =====================================================================
# C19 -- convert_corpus must convert/flag .tsv, .rtf and .ltx as editable
# =====================================================================

def test_c19_convert_corpus_exts():
    sub = scratch("nbt_audit_cc_")
    write(sub / "table.tsv", "a\tb\n")
    write(sub / "note.rtf", "{\\rtf1\\ansi plain}\n")
    write(sub / "paper.ltx", "\\documentclass{article}\n")
    work = sub / "work"
    proc = run_py(WS / "nbt-skills/nbt-review/scripts/convert_corpus.py",
                  "--submission", sub, "--work", work)
    inv = json.loads((work / "inventory.json").read_text(encoding="utf-8"))
    entries = {(e.get("path") or e.get("file") or "").replace("\\", "/"): e
               for e in (inv if isinstance(inv, list) else inv.get("entries", []))}
    bad = {n: entries.get(n, {}).get("editable") for n in ("table.tsv", "note.rtf", "paper.ltx")
           if not entries.get(n, {}).get("editable")}
    check("C19 .tsv/.rtf/.ltx are converted and marked editable", not bad
          and proc.returncode == 0, f"rc={proc.returncode} bad={bad} keys={sorted(entries)[:6]}")


# =====================================================================
# M1 -- two processes must not both reclaim one stale pipeline lock
# =====================================================================

LOCK_RACE_CHILD = r'''
import importlib.util, os, sys, time
from pathlib import Path

spec = importlib.util.spec_from_file_location("nbt_race", sys.argv[1])
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_race"] = nb
spec.loader.exec_module(nb)

delay = float(sys.argv[4])
real_read = nb.read_json


def slow_read(path, *a, **k):
    out = real_read(path, *a, **k)
    if str(path).endswith(nb.LOCK_FILE):
        time.sleep(delay)          # widen the reclaim window deterministically
    return out


nb.read_json = slow_read
ctx = nb.Ctx(Path(sys.argv[2]))
log = Path(sys.argv[3])
try:
    with ctx.lock("race"):
        with open(log, "a", encoding="utf-8") as f:
            f.write("acquired %d %f\n" % (os.getpid(), time.time()))
            f.flush()
        time.sleep(2.0)            # outlast the slower reclaimer's 0.8 s delay
        with open(log, "a", encoding="utf-8") as f:
            f.write("released %d %f\n" % (os.getpid(), time.time()))
except SystemExit:
    sys.exit(3)
'''


def test_m01_lock_reclaim_race():
    tmp = scratch("nbt_audit_m1_")
    root = tmp / "root"
    root.mkdir()
    write(root / "_pipeline.lock", json.dumps({"pid": 10 ** 9, "what": "stale"}))
    child = tmp / "race_child.py"
    write(child, LOCK_RACE_CHILD)
    log = tmp / "acquired.log"
    procs = [subprocess.Popen([sys.executable, str(child), str(WS / "nbt_pipeline.py"),
                               str(root), str(log), delay],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for delay in ("0.2", "0.8")]
    for p in procs:
        p.wait(timeout=120)
    holds = []
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 3:
                holds.append((parts[0], int(parts[1]), float(parts[2])))
    started = {pid: ts for what, pid, ts in holds if what == "acquired"}
    released = {pid: ts for what, pid, ts in holds if what == "released"}
    overlap = any(a in released and b in released and started[b] < released[a]
                  for a in started for b in started if a < b)
    check("M1 two stale-lock reclaimers never hold the lock at the same time",
          len(started) == 1 and not overlap and sorted(p.returncode for p in procs) == [0, 3],
          f"acquirers={sorted(started)} overlap={overlap} "
          f"rcs={[p.returncode for p in procs]}")


REV_SCRIPTS = WS / "nbt-skills" / "nbt-review" / "scripts"


def _corpus(tmp: Path, files: dict) -> Path:
    work = tmp / "work"
    (work / "corpus").mkdir(parents=True)
    for name, text in files.items():
        write(work / "corpus" / name, text)
    return work


def _artifact(tmp: Path, name: str):
    path = tmp / "artifacts" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def test_m07_m14_extractors():
    # M7 -- a heading-less reference-list file must not be swept as prose
    tmp = scratch("nbt_audit_m7_")
    work = _corpus(tmp, {"refs.md.txt": "1. Smith J. A title. Nature. 2020.\n"
                                       "2. Doe A. Another. Science. 2021.\n",
                         "manuscript.md.txt": "Validated [1] and reused [3].\n"})
    proc = run_py(REV_SCRIPTS / "extract_citations.py", "--work", work)
    art = _artifact(tmp, "M2_citations.json") or {}
    check("M7 a reference-role file without a heading is parsed as a reference list",
          proc.returncode == 0 and [e["num"] for e in art.get("ref_entries", [])] == [1, 2]
          and art.get("orphan_callouts") == [3],
          f"refs={[e.get('num') for e in art.get('ref_entries', [])]} "
          f"orphans={art.get('orphan_callouts')}")

    # M8 -- a supplemental bibliography is not the authors' own metric source
    tmp = scratch("nbt_audit_m8_")
    work = _corpus(tmp, {"suppAll-d.bib.txt": "@article{x, note={62% of cases}}\n",
                         "main.md.txt": "The result was 62% in our cohort.\n"})
    run_py(REV_SCRIPTS / "extract_numbers.py", "--work", work)
    art = _artifact(tmp, "M4_numbers.json") or {}
    files = {o["file"] for m in art.get("metrics", []) for o in m.get("occurrences", [])}
    check("M8 a .bib file contributes no M4 metrics", files == {"main.md.txt"}, str(sorted(files)))

    # M9 -- a cross-reference parenthetical is not an expansion
    tmp = scratch("nbt_audit_m9_")
    work = _corpus(tmp, {"main.md.txt": "We ran PCR (see Fig. 2) in the assay. PCR was repeated.\n"})
    run_py(REV_SCRIPTS / "extract_acronyms.py", "--work", work)
    art = _artifact(tmp, "M1_acronyms.json") or []
    pcr = next((r for r in art if r.get("acronym") == "PCR"), {})
    check("M9 'PCR (see Fig. 2)' is not recorded as a definition",
          "see Fig. 2" not in (pcr.get("expansions") or [])
          and pcr.get("defined_at_first_use") == "never",
          f"expansions={pcr.get('expansions')} defined={pcr.get('defined_at_first_use')}")

    # M10 -- a quoted long form does not consume the first-use slot
    tmp = scratch("nbt_audit_m10_")
    work = _corpus(tmp, {"main.md.txt":
                         'See "Copy-number analysis of single cells" for a review.\n'
                         "We repeated copy-number analysis of single cells in validation.\n"
                         "Copy-number analysis of single cells (CN) was performed.\n"})
    run_py(REV_SCRIPTS / "extract_acronyms.py", "--work", work)
    art = _artifact(tmp, "M1_acronyms.json") or []
    cn = next((r for r in art if r.get("acronym") == "CN"), {})
    check("M10 the quoted title is counted, not listed as residue",
          cn.get("long_form_after_first_use_total") == 0
          and (cn.get("long_form_quoted_skipped") or {}).get("main text") == 1
          and cn.get("long_form_first_use", {}).get("main text", "").endswith(":2"),
          f"rows={cn.get('long_form_after_first_use_total')} "
          f"quoted={cn.get('long_form_quoted_skipped')} first={cn.get('long_form_first_use')}")

    # M11 -- a "References are ..." prose line stays in the sweep
    tmp = scratch("nbt_audit_m11_")
    work = _corpus(tmp, {"main.md.txt": "References are available. HLA-DR was measured. n = 5.\n"})
    run_py(REV_SCRIPTS / "extract_numbers.py", "--work", work)
    art = _artifact(tmp, "M4_numbers.json") or {}
    labels = {(m.get("label"), m.get("value")) for m in art.get("metrics", [])}
    check("M11 a prose line starting with 'References' is not skipped", ("n", "5") in labels,
          str(sorted(labels)))

    # M12 -- a missing corpus is an error, never a silent zero
    tmp = scratch("nbt_audit_m12_")
    work = _corpus(tmp, {"x.md.txt": "n = 5.\n"})
    shutil.rmtree(work / "corpus")
    proc = run_py(REV_SCRIPTS / "extract_occurrences.py", "--work", work, "--value", "5")
    check("M12 a missing corpus exits 2 like the sibling extractors",
          proc.returncode == 2 and "corpus dir not found" in proc.stdout, proc.stdout[-80:])

    # M13/M14 -- comma-form CI, mandatory R2 exponent, CI level is not a percentage
    tmp = scratch("nbt_audit_m13_")
    work = _corpus(tmp, {"main.md.txt": "(95% CI, 0.2-0.5) and r = 0.8 and R2 = 0.9.\n"})
    run_py(REV_SCRIPTS / "extract_numbers.py", "--work", work)
    art = _artifact(tmp, "M4_numbers.json") or {}
    labels = {(m.get("label"), m.get("value")) for m in art.get("metrics", [])}
    check("M13 the AMA comma-form CI is inventoried", ("CI", "0.2-0.5") in labels, str(sorted(labels)))
    check("M14 a plain r is not labelled R2 and the CI level is not a percentage",
          ("R2", "0.9") in labels and ("R2", "0.8") not in labels
          and not any(lbl == "percentage" for lbl, _v in labels), str(sorted(labels)))


def test_l02_l04_l05_l09_l11():
    # L2 -- an agent's literal "NaN" survives a state.json round trip
    tmp = scratch("nbt_audit_l2_")
    path = tmp / "state.json"
    nb.write_json_atomic(path, {"scores": {"judge": {"note": "NaN"}}, "sentinel": float("-inf")})
    obj = nb.read_json(path)
    check("L2 an agent string 'NaN' is not revived to a float in state.json",
          isinstance(obj["scores"]["judge"]["note"], str)
          and obj["scores"]["judge"]["note"] == "NaN" and obj["sentinel"] == float("-inf"),
          str(obj))

    # L4 -- "configured" requires the command to be startable
    home = scratch("nbt_audit_l4_")
    script = home / "server.py"
    write(script, "x = 1\n")
    old_home = os.environ.get("CODEX_HOME")
    os.environ["CODEX_HOME"] = str(home)
    try:
        write(home / "config.toml",
              "[mcp_servers.docx-converter]\ncommand = \"no-such-binary-xyz\"\n"
              f"args = [\"{script}\"]\n")
        fake = nb.mcp_server_configured("docx-converter")
        write(home / "config.toml",
              f"[mcp_servers.docx-converter]\ncommand = \"{sys.executable}\"\n"
              f"args = [\"{script}\"]\n")
        real = nb.mcp_server_configured("docx-converter")
    finally:
        if old_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = old_home
    check("L4 a missing command binary is not 'configured'", fake is False and real is True,
          f"fake={fake} real={real}")

    # L5 -- a round whose base cannot be materialized is a clean, NAMED failure,
    # never a traceback. Two situations are distinguishable now: an earlier
    # round that is simply not done yet (which `run --only R` can produce, so
    # the message names the missing dependency and `drive_round` returns
    # incomplete instead of dying), and an earlier round marked done whose pin
    # record is gone (a corrupt root, which still dies with the plain message).
    tmp = scratch("nbt_audit_l5_")
    src = tmp / "source"
    src.mkdir()
    write(src / "ms.md", "Abstract\n\nhello world\n\nMethods\n\nx\n")
    root = tmp / "root"
    subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), "setup", "--source", str(src),
                    "--root", str(root), "--rounds", "2", "--judges", "1", "--rewrites", "1",
                    "--revises", "1"], capture_output=True, text=True, check=True)
    ctx = nb.Ctx(root)
    ctx.load()
    nb.materialize_a1(ctx, 1)
    ctx.save_state()
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ok, _paused = nb.drive_round(ctx, 2, cmd=[sys.executable, "-c", "pass"],
                                         timeout=5, jobs=1, retries=0, manual=False,
                                         nowait=True, poll=1, redline=False)
        clean = (ok is False and "round 2 base is not ready yet" in out.getvalue()
                 and "round 1 is pending" in out.getvalue())
        detail = (out.getvalue() + err.getvalue()).strip()[:160]
    except SystemExit as exc:
        clean = "cannot materialize the round 2 base" in err.getvalue()
        detail = err.getvalue().strip()[:100]
    except Exception as exc:                                     # noqa: BLE001
        clean = False
        detail = f"raw {type(exc).__name__}: {exc}"[:100]
    check("L5 an un-materializable round base fails cleanly", clean, detail)

    # L9/L11 -- a dangling shared-string index and a UTF-16 .txt
    tmp = scratch("nbt_audit_l9_")
    xlsx = tmp / "t.xlsx"
    import zipfile
    with zipfile.ZipFile(xlsx, "w") as z:
        z.writestr("xl/workbook.xml",
                   '<workbook><sheets><sheet name="S1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships><Relationship Id="rId1" Type="http://schemas.openxmlformats.org'
                   '/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '</Relationships>')
        z.writestr("xl/sharedStrings.xml", "<sst><si><t>alpha</t></si></sst>")
        z.writestr("xl/worksheets/sheet1.xml",
                   '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>3</v></c></row>'
                   "</sheetData></worksheet>")
    cc = _load_script("convert_corpus", REV_SCRIPTS / "convert_corpus.py")
    text, _notes = cc.xlsx_to_text(str(xlsx))
    check("L9 a dangling shared-string index renders empty, never its own number",
          "3" not in text.split("S1")[-1], repr(text))
    txt = tmp / "u.txt"
    txt.write_bytes("HLA-DR was measured.\n".encode("utf-16"))
    decoded, _notes = cc.plain_copy(str(txt))
    check("L10 a UTF-16 BOM text file decodes instead of mojibake",
          decoded.strip() == "HLA-DR was measured.", repr(decoded[:40]))

    # L11 -- occurrence values: no thousands-separator false positive, U+2212 found
    tmp = scratch("nbt_audit_l11_")
    work = _corpus(tmp, {"main.md.txt": "5,000 cells, 5 sampled and 3.1 \u00d7 10\u22122.\n"})
    run_py(REV_SCRIPTS / "extract_occurrences.py", "--work", work, "--value", "5")
    art = json.loads((work / "occurrences_5.json").read_text(encoding="utf-8"))
    matches = [o["match"] for o in art[0]["occurrences"]]
    check("L11 value 5 does not match inside 5,000", matches == ["5"], str(matches))
    run_py(REV_SCRIPTS / "extract_occurrences.py", "--work", work, "--value", "0.031")
    art = json.loads((work / "occurrences_0_031.json").read_text(encoding="utf-8"))
    check("L11 the U+2212 scientific form is enumerated",
          [o["match"] for o in art[0]["occurrences"]] == ["3.1 \u00d7 10\u22122"],
          str([o["match"] for o in art[0]["occurrences"]]))
    work2 = _corpus(scratch("nbt_audit_l7c_"),
                    {"main.tex.txt": "Value $3.1 \\times 10^{-2}$ and 3.1 \u00d7 10\u207b\u00b2.\n"})
    run_py(REV_SCRIPTS / "extract_occurrences.py", "--work", work2, "--value", "0.031")
    art = json.loads((work2 / "occurrences_0_031.json").read_text(encoding="utf-8"))
    matched = {o["match"] for o in art[0]["occurrences"]}
    check("L11 LaTeX \\times and unicode-superscript forms are enumerated",
          any(r"\times" in m for m in matched) and any("\u207b\u00b2" in m for m in matched),
          str(sorted(matched)))


def test_l25_cover_letter_and_occurrence_guards():
    # L25 -- a broken symlink at OUT is cleared, not written through
    tmp = scratch("nbt_audit_l25_")
    out = tmp / "out.docx"
    out.symlink_to(tmp / "missing-target.docx")
    adapter = _load_script("redlines_l25", WS / "nbt_redlines_adapter.py")
    base = tmp / "base.docx"
    revised = tmp / "revised.docx"
    write(base, "x")
    write(revised, "y")
    try:
        adapter.clear_out(str(out))
        cleared = not os.path.lexists(out)
        detail = ""
    except SystemExit as exc:                                    # noqa: BLE001
        cleared, detail = False, str(exc)
    check("L25 a dangling OUT symlink is removed before conversion", cleared, detail)

    # cover-letter mode answers with a row instead of silence
    tmp = scratch("nbt_audit_letter_")
    write(tmp / "notes.md", "Title page\n\nHLA-DR was measured.\n")
    proc = run_py(REV_SCRIPTS / "count_words.py", tmp / "notes.md",
                  "--section", "cover-letter", "--json")
    rows = json.loads(proc.stdout)["rows"] if proc.returncode == 0 else []
    check("cover-letter mode reports a non-letter file instead of an empty result",
          rows and rows[0]["section"] == "not a cover letter", str(rows)[:120])

    # a malformed --variants-file is an error, not a traceback
    tmp = scratch("nbt_audit_var_")
    work = _corpus(tmp, {"main.md.txt": "n = 5.\n"})
    bad = tmp / "bad.json"
    write(bad, "{not json")
    proc = run_py(REV_SCRIPTS / "extract_occurrences.py", "--work", work,
                  "--variants-file", bad)
    check("a malformed variants file exits 2 with the tool's error style",
          proc.returncode == 2 and "cannot read variants file" in proc.stdout,
          f"rc={proc.returncode} {proc.stdout[-60:]!r}")


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    for fn in (test_c01_python310_parse, test_c02_visual_gate, test_c03_length_anchoring,
               test_c04_cover_letter, test_c05_c06_revision_token, test_c07_empty_ledger,
               test_c08_counter_renames, test_c09_token_tool_missing_dir,
               test_c10_raw_scores_label, test_c12_citations_uncited,
               test_c13_rtf_surrogates, test_c14_roman_lookalikes, test_c15_guess_role,
               test_c16_docx2pdf_paths, test_c17_redlines_adapter,
               test_c18_caption_subtraction, test_c19_convert_corpus_exts,
               test_m01_lock_reclaim_race, test_m07_m14_extractors,
               test_l02_l04_l05_l09_l11, test_l25_cover_letter_and_occurrence_guards):
        try:
            fn()
        except Exception as e:                                   # noqa: BLE001
            check(f"{fn.__name__} completed", False, f"{type(e).__name__}: {e}")
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL AUDIT-REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

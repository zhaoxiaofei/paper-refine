#!/usr/bin/env python3
"""Acronym long-form (M1b / rule (k)) revision fix — red on the pre-fix tree.

The reported bug: "copy-number (CN)" is introduced at first use, yet the
manuscript main text keeps spelling the term out ("copy-number", "copy number",
"copy numbers"). Nothing revised it because the M1 sweep enumerated only
acronym-like TOKENS: the row for CN read "defined at first use: Y, consistent:
Y" while the long form carried the prose. This suite covers the whole chain of
the fix:

  A. detection — extract_acronyms.py's M1b instance table finds the residues,
     including when the definition lives in another context/file;
  B. context rules — first long-form use per context is legitimate, quoted
     titles are never rows, abbreviation-key entries count as definitions;
  C. precision — another term's definition site, bibliographies and atomic
     single-word expansions never produce rows; repeated page furniture is
     annotated;
  D. closed loop — after the P1a substitution (acronym replaces the residue)
     the SAME sweep reports zero rows for the edited context;
  E. wiring — the review spec (rule (k)), the revise spec (P1a), both prompts'
     appendices, the pipeline's revise/judge directives and the orchestrator's
     "M1b rows were audited" gate.

Run:  python3 .nbt_test/test_acronym_longform.py
`NBT_WS` retargets the harness at a baseline copy (pre-fix -> red),
`NBT_SKILLS` at another skills pack.
"""
import importlib.util
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
SKILLS = Path(os.environ.get("NBT_SKILLS") or WS / "nbt-skills")
SCRIPTS = SKILLS / "nbt-review" / "scripts"

spec = importlib.util.spec_from_file_location("nbtp", WS / "nbt_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["nbtp"] = np
spec.loader.exec_module(np)

FAILS = []
_TMPDIRS: list = []


@atexit.register
def _cleanup_tmpdirs() -> None:
    for d in _TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def scratch(prefix: str) -> Path:
    """mkdtemp removed when the suite exits (no per-run scratch leaks)."""
    p = Path(tempfile.mkdtemp(prefix=prefix))
    _TMPDIRS.append(p)
    return p


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def run_script(script, *args):
    p = subprocess.run([sys.executable, str(SCRIPTS / script)] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        print(f"   !! {script} exited {p.returncode}: {(p.stdout + p.stderr).strip()[:300]}")
    return p


def sweep(files, name="case"):
    """Convert `files` ({relpath: text}) and run the M1 sweep; return (rows, md, dirs)."""
    tmp = scratch(f"nbt_acr_{name}_")
    sub, work, out = tmp / "sub", tmp / "work", tmp / "out"
    for rel, text in files.items():
        p = sub / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    run_script("convert_corpus.py", "--submission", sub, "--work", work)
    p = run_script("extract_acronyms.py", "--work", work, "--out", out)
    rows = {}
    jp = out / "artifacts" / "M1_acronyms.json"
    if jp.is_file():
        rows = {r["acronym"]: r for r in json.loads(jp.read_text(encoding="utf-8"))}
    md = (out / "artifacts" / "M1_acronyms.md")
    md = md.read_text(encoding="utf-8") if md.is_file() else ""
    return rows, md, (sub, work, out), p


def m1b_rows(md):
    """The M1b instance-table data rows, as cell lists."""
    lines = md.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().startswith("## M1b")), None)
    if start is None:
        return []
    out = []
    for ln in lines[start:]:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells or not cells[0] or cells[0] in ("acronym", "—") \
                or set(cells[0]) <= set("-: "):
            continue
        out.append(cells)
    return out


def appendix(text, heading, next_heading=None):
    lines = text.split("\n")
    start = next((i + 1 for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    if start is None:
        return ""
    end = len(lines)
    if next_heading:
        end = next((j for j in range(start, len(lines)) if lines[j].startswith(next_heading)), end)
    return "\n".join(lines[start:end]).strip()


# --------------------------------------------------------------------------
# A. detection: the reported bug itself
# --------------------------------------------------------------------------
DEF_THEN_RESIDUE = {
    "01_abstract.md": "Abstract\n\nCopy-number (CN) alterations drive cancer progression.\n",
    "02_main.md": (
        "Results\n\n"
        "We analysed copy-number profiles and copy number gains.\n"
        "The CN calling was robust, but copy-number analysis revealed copy-number "
        "changes.\n"
        "Copy-Number variation was also studied.\n"),
}

rows, md, dirs, proc = sweep(DEF_THEN_RESIDUE, "reported")
cn = rows.get("CN") or {}
cn_rows = m1b_rows(md)

check("A1 abstract-defined CN is audited in another context",
      proc.returncode == 0 and cn.get("long_form_after_first_use_total", 0) == 4,
      f"rows={cn.get('long_form_after_first_use_total')} per-context="
      f"{ {k: len(v) for k, v in (cn.get('long_form_after_first_use') or {}).items()} }")

check("A2 the residue rows are in the main text, not the definition context",
      [c for c in cn_rows if c[0] == "CN"] and
      all(c[1] == "main text" and c[2].startswith("02_main.md.txt:") for c in cn_rows),
      f"rows={[(c[1], c[2]) for c in cn_rows]}")

check("A3 variant-tolerant: space, hyphen, capital and plural all matched",
      {"copy number", "copy-number", "Copy-Number"} <= set(cn.get("long_form_variants_seen") or []),
      f"variants={cn.get('long_form_variants_seen')}")

check("A4 the definition site is the context's first use, never a row",
      cn.get("long_form_first_use", {}).get("abstract", "").endswith("01_abstract.md.txt:3")
      and not any(c[2].startswith("01_abstract.md.txt") for c in cn_rows),
      f"first={cn.get('long_form_first_use')} rows={[c[2] for c in cn_rows]}")

check("A5 markdown table rows and JSON totals agree",
      len(cn_rows) == cn.get("long_form_after_first_use_total") == 4,
      f"md={len(cn_rows)} json={cn.get('long_form_after_first_use_total')}")

# A6 must exercise the empty-table wording on a corpus that actually has no
# residue; on the A1 fixture cn_rows is non-empty, so the old `else True` made
# the message path untestable.
_rows6, md6, _d6, _p6 = sweep(
    {"ms.md": "Abstract\n\nHLA-DR was measured.\n\nResults\n\nHLA-DR stayed high.\n"},
    "clean")
check("A6 no reported long-form residue means an empty M1b table",
      "no long-form re-use detected" in md6 and not m1b_rows(md6),
      md6[md6.find("## M1b"):][:120])

# A capitalized long form doubles as an acronym-like token ("Copy-Number").
# The matcher must not drop the candidate as "another acronym" -- that bug made
# the whole CN audit disappear on exactly this input.
rows2, md2, _d2, proc2 = sweep(
    {"ms.md": "Abstract\n\nCopy-Number (CN) burden was measured.\n"
              "Results\n\nWe compared Copy-Number profiles with Copy-Number gains.\n"},
    "cased")
cn2 = rows2.get("CN") or {}
check("A7 a capitalized long form is still audited (token-suppression bug)",
      cn2.get("long_form_after_first_use_total", 0) == 1
      and cn2.get("long_form_variants_seen", []) == ["Copy-Number"],
      f"rows={cn2.get('long_form_after_first_use_total')} "
      f"variants={cn2.get('long_form_variants_seen')}")

# --------------------------------------------------------------------------
# B. context rules
# --------------------------------------------------------------------------
rows3, md3, _d3, _p3 = sweep(
    {"01_paper.md": "Abstract\n\nWhole-genome sequencing (WGS) was used.\n"
                    "Results\n\nWGS was performed.\n"},
    "firstuse")
wgs3 = rows3.get("WGS") or {}
check("B1 an acronym alone (no long-form re-use) yields zero M1b rows",
      wgs3.get("long_form_after_first_use_total", 0) == 0,
      f"rows={wgs3.get('long_form_after_first_use_total')}")

rows4, md4, _d4, _p4 = sweep(
    {"01_abstract.md": "Abstract\n\nCopy-number (CN) alterations are common.\n",
     "figs.md": "Fig. 1 | copy-number heatmap of the cohort.\n"
                "Fig. 2 | copy-number gains across cells.\n"},
    "legend")
fig4 = m1b_rows(md4)
check("B2 per-context first use is exempt, the next mention in that context is a row",
      len(fig4) == 1 and fig4[0][0] == "CN" and fig4[0][1] == "figure legend",
      f"rows={fig4}")

rows5, md5, _d5, _p5 = sweep(
    {"abstract.md": "Abstract\n\nCopy-number (CN) alterations are common.\n",
     "main.md": "Results\n\nWe scored copy-number burden per cell.\n"
                "The copy-number profile was then compared across cells.\n"},
    "otherctx")
cn5 = rows5.get("CN") or {}
check("B3 a definition in another context still audits this context's residues",
      cn5.get("long_form_after_first_use_total", 0) == 1,
      f"rows={cn5.get('long_form_after_first_use_total')} "
      f"per-ctx={ {k: len(v) for k, v in (cn5.get('long_form_after_first_use') or {}).items()} }")

rows6, md6, _d6, _p6 = sweep(
    {"legend.md": "Fig. 3 | Hap_0: haploid ground truth. CN, copy number; "
                  "PCC, Pearson correlation coefficient.\n"
                  "The CN caller reported a copy number gain.\n"},
    "key")
cn6 = rows6.get("CN") or {}
pcc6 = rows6.get("PCC") or {}
key_rows = [c for c in m1b_rows(md6) if c[2].startswith("legend.md.txt:1")]
check("B4 the abbreviation key 'CN, copy number' is a definition, never a row",
      cn6.get("defined_at_first_use") == "Y" and key_rows == []
      and cn6.get("long_form_after_first_use_total", 0) == 1,
      f"defined={cn6.get('defined_at_first_use')} key_rows={key_rows} "
      f"rows={cn6.get('long_form_after_first_use_total')}")
check("B5 the key form also defines the second entry (PCC)",
      pcc6.get("defined_at_first_use") == "Y" and pcc6.get("expansions") ==
      ["Pearson correlation coefficient"],
      f"pcc={pcc6.get('expansions')}")

# --------------------------------------------------------------------------
# C. precision
# --------------------------------------------------------------------------
rows7, _md7, _d7, _p7 = sweep(
    {"ms.md": "Abstract\n\nCopy-number (CN) states were called.\n"
              "Results\n\nWe scored copy-number states per cell.\n"
              "We compared the CN states with those in "
              "\u201cCopy-number analysis of single cells\u201d (ref. 3).\n"
              "A third copy-number check followed.\n"},
    "quoted")
cn7 = rows7.get("CN") or {}
check("C1 a quoted title is counted, never listed as a residue row",
      cn7.get("long_form_after_first_use_total", 0) == 1
      and sum((cn7.get("long_form_quoted_skipped") or {}).values()) == 1,
      f"rows={cn7.get('long_form_after_first_use_total')} "
      f"quoted={cn7.get('long_form_quoted_skipped')}")

rows8, _md8, _d8, _p8 = sweep(
    {"ms.md": "Abstract\n\nCopy-number alterations (CNAs) and CNVs were profiled.\n"
              "Results\n\nCN calling was robust; copy-number variations (CNVs) were "
              "called too.\n"},
    "otherdef")
cn8 = rows8.get("CN") or {}
check("C2 another acronym's definition site is not a CN residue row",
      all(c[3] != "copy-number" for c in m1b_rows(_md8) if c[0] == "CN"),
      f"rows={[(c[0], c[3]) for c in m1b_rows(_md8)]}")

rows9, md9, _d9, _p9 = sweep(
    {"ms.md": "Abstract\n\nCopy-number (CN) states were called.\n"
              "Results\n\nWe benchmarked copy-number inference.\n"
              "We benchmarked copy-number inference.\n"
              "We benchmarked copy-number inference.\n"},
    "furniture")
furn = [c for c in m1b_rows(md9) if c[0] == "CN"]
check("C3 repeated identical lines carry a page-furniture annotation",
      len(furn) == 2 and all("same line x3" in c[4] for c in furn),
      f"rows={[(c[2], c[4][-24:]) for c in furn]}")

rows10, md10, _d10, _p10 = sweep(
    {"refs.bib": "@article{x,\n  title = {A study of copy-number variation},\n"
                 "  abstract = {We used copy-number profiling in 100 samples.}\n}\n",
     "ms.md": "Abstract\n\nCopy-number (CN) states were called.\n"},
    "bib")
check("C4 a bibliography file feeds neither the token inventory nor M1b",
      "CN" in rows10 and not m1b_rows(md10)
      and not any(r["files"] and any("refs.bib" in f for f in r["files"])
                  for r in rows10.values()),
      f"tokens={sorted(rows10)} rows={m1b_rows(md10)}")

# --------------------------------------------------------------------------
# D. closed loop: fix the residue, the rescan goes green
# --------------------------------------------------------------------------
FIXED = dict(DEF_THEN_RESIDUE)
FIXED["02_main.md"] = (
    "Results\n\n"
    "We analysed copy-number profiles and CN gains.\n"
    "The CN calling was robust, but CN analysis revealed CN changes.\n"
    "CN variation was also studied.\n")
rows11, md11, _d11, _p11 = sweep(FIXED, "fixed")
cn11 = rows11.get("CN") or {}
check("D1 after the P1a substitution the M1b table is empty for that acronym",
      cn11.get("long_form_after_first_use_total", 0) == 0 and m1b_rows(md11) == [],
      f"rows={cn11.get('long_form_after_first_use_total')}")

# --------------------------------------------------------------------------
# E. spec + orchestration wiring
# --------------------------------------------------------------------------
sw = (SKILLS / "nbt-review" / "references" / "sweeps.md").read_text(encoding="utf-8")
er = (SKILLS / "nbt-revise" / "references" / "edit_rules.md").read_text(encoding="utf-8")
ip = (SKILLS / "prompts" / "identify_issues.prompt.md").read_text(encoding="utf-8")
ap = (SKILLS / "prompts" / "adress_issues.prompt.md").read_text(encoding="utf-8")
check("E1 sweeps.md carries rule M1(k) and the M8 carve-out",
      "- (k) the un-abbreviated long form is used again" in sw
      and "Acronym long-form/short-form pairs are NOT M8 variants" in sw
      and "is rule (k), not (c)" in sw)
check("E2 edit_rules.md carries the P1a fix direction and the rescan gate",
      "## P1a — Acronym long-form repetition (review check M1, rule (k))" in er
      and "must show ZERO rows for the contexts you\n  edited" in er)
check("E3 prompt appendices stay verbatim in sync with the references",
      appendix(ip, "## APPENDIX: Sweeps", "## APPENDIX: Discovery") == sw.strip()
      and appendix(ap, "## APPENDIX: Edit rules") == er.strip())
check("E4 the M1 script-table line documents the M1b audit",
      "M1b long-form audit" in (SKILLS / "nbt-review" / "SKILL.md").read_text(encoding="utf-8")
      and "M1b long-form audit" in ip)

revise = np.revise_prompt(Path("/tmp/x"), "r1_a2_revise", 1)
judge = np.judge_prompt(Path("/tmp/x"), "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"])
check("E5 the revise prompt carries the rule-(k) recipe and the zero-M1b gate",
      "Acronym long-form repetition" in revise and "copy numbers -> CNs" in revise
      and "ZERO rows for the contexts you edited" in revise)
check("E6 the judge prompt names the consistency tier (not cosmetic) with M1b",
      "Systematic consistency failures are NOT cosmetic" in judge
      and "M1b instance table" in judge)


def fake_review_sandbox(tmp, m1_md, findings, coverage):
    sb = Path(tmp)
    art = sb / "review" / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / "M1_acronyms.md").write_text(m1_md, encoding="utf-8")
    return sb, {"submission_dir": "./base", "guidelines_source": "x",
                "findings": findings, "artifacts": {}, "coverage": coverage}


def full_coverage(detail=None):
    detail = detail or {}
    return ([{"check": c, "disposition": detail.get(c, "clean -- basis: x")}
             for c in [f"M{i}" for i in range(1, 18)] + [f"J{i}" for i in range(1, 5)]]
            + [{"check": c, "disposition": detail.get(c, "clean -- basis: x")}
               for c in ("M18", "M19", "M20", "M21", "M22", "M23", "M24")])


M1B_MD = ("# M1\n\n| acronym | ... |\n|---|---|\n\n"
          "## M1b — LONG FORMS RE-USED AFTER THEIR FIRST USE (rule M1(k); one row = one finding)\n\n"
          "| acronym | context | file:line | long form as written | excerpt |\n"
          "|---|---|---|---|---|\n"
          "| CN | main text | ms.txt:12 | copy-number | We analysed copy-number profiles |\n")
ctx = np.Ctx(Path("/tmp/x"))
ctx.cfg = {}
tmp1 = scratch("nbt_gate1_")
errs1 = []
np.check_review_contract(ctx, *fake_review_sandbox(
    tmp1, M1B_MD, [], full_coverage()), errs1, [])
check("E7 orchestrator gate: an M1b table with rows and no M1 finding fails",
      any("M1b long-form row" in e for e in errs1), f"errs={str(errs1)[:160]}")

tmp2 = scratch("nbt_gate2_")
errs2 = []
np.check_review_contract(ctx, *fake_review_sandbox(
    tmp2, M1B_MD, [{"id": "F-1", "check": "M1"}], full_coverage()), errs2, [])
check("E8 orchestrator gate: an M1 finding clears it", not errs2, f"errs={str(errs2)[:160]}")

tmp3 = scratch("nbt_gate3_")
errs3 = []
np.check_review_contract(ctx, *fake_review_sandbox(
    tmp3, M1B_MD, [], full_coverage({"M1": "clean -- basis: M1_acronyms.md; all 1 M1b row "
                                           "disposed OK: quoted title"})), errs3, [])
check("E9 orchestrator gate: a coverage row that accounts for M1b clears it",
      not errs3, f"errs={str(errs3)[:160]}")

tmp4 = scratch("nbt_gate4_")
errs4 = []
np.check_review_contract(ctx, *fake_review_sandbox(
    tmp4, "# M1\n\n| acronym |\n|---|\n| CN |\n", [], full_coverage()), errs4, [])
check("E10 orchestrator gate ignores an M1 artifact without M1b rows",
      not errs4 and getattr(np, "m1b_row_count", lambda _t: -1)(M1B_MD) == 1
      and getattr(np, "m1b_row_count", lambda _t: -1)("# M1\n\n| acronym |\n|---|\n| CN |\n") == 0,
      f"errs={str(errs4)[:120]}")


def coverage_m1(disposition="clean -- basis: x", detail=""):
    """The E-suite coverage table with M1's own two cells under test."""
    out = []
    for r in full_coverage():
        if r["check"] == "M1":
            r = {"check": "M1", "disposition": disposition, "detail": detail}
        out.append(r)
    return out


# The 2026-09-22 root (round 1, second attempt): the session rewrote the seeded
# table with a `#` numbering column and a `disposition` column, disposed all 25
# rows with their own reasons, and recorded the table + the count in the M1
# coverage row's DETAIL cell. The gate read only the `disposition` cell and
# failed a session that had followed the prompt ("a recorded reason in the M1
# coverage detail"); it also counted the `#` header row as a 26th instance.
M1B_DISPOSED_MD = (
    "## M1b — un-abbreviated long forms used again after the acronym's first use\n\n"
    "| # | acronym | context | location | long form as written | disposition |\n"
    "|---|---|---|---|---|---|\n"
    "| 1 | CN | cover letter | letter.txt:4 | copy-number | OK — M1(k) does not apply: the "
    "cover letter never defines the short form. |\n"
    "| 2 | CN | supplementary | supp.tex.txt:109 | copy-number | OK — the match is the "
    "manuscript TITLE inside \\title{}, which must stay verbatim. |\n")
M1B_BARE_OK_MD = (
    "## M1b — long-form residues\n\n"
    "| acronym | context | file:line | long form as written | disposition |\n"
    "|---|---|---|---|---|\n"
    "| CN | main text | ms.txt:12 | copy-number | OK |\n")

tmp5 = scratch("nbt_gate5_")
errs5 = []
np.check_review_contract(ctx, *fake_review_sandbox(
    tmp5, M1B_DISPOSED_MD, [],
    coverage_m1("clean — basis: the artifact's rows are all disposed",
                "artifact M1_acronyms.md, 377 token rows + 25 M1b rows; script over the "
                "field-stripped corpus")), errs5, [])
check("E11 orchestrator gate reads the M1 coverage row's detail cell (the run's own shape)",
      not errs5, f"errs={str(errs5)[:200]}")

tmp6 = scratch("nbt_gate6_")
errs6 = []
np.check_review_contract(ctx, *fake_review_sandbox(
    tmp6, M1B_DISPOSED_MD, [], coverage_m1()), errs6, [])
check("E12 orchestrator gate accepts the skill's own route: every table row disposes itself",
      not errs6, f"errs={str(errs6)[:200]}")

tmp7 = scratch("nbt_gate7_")
errs7 = []
np.check_review_contract(ctx, *fake_review_sandbox(
    tmp7, M1B_BARE_OK_MD, [], coverage_m1()), errs7, [])
check("E13 a '#' header is not an instance and a bare OK is not a recorded reason",
      getattr(np, "m1b_row_count", lambda _t: -1)(M1B_DISPOSED_MD) == 2
      and getattr(np, "m1b_rows_disposed", lambda _t: True)(M1B_DISPOSED_MD)
      and not getattr(np, "m1b_rows_disposed", lambda _t: True)(M1B_BARE_OK_MD)
      and np.m1b_row_count(M1B_BARE_OK_MD) == 1
      and any("M1b long-form row" in e for e in errs7),
      f"errs={str(errs7)[:160]}")

# The sweep script's own empty-table row (`| — | — | — | — | no long-form re-use
# detected |`) is a placeholder, never an instance: counting it made the gate
# demand an M1 finding for a clean table.
M1B_EMPTY_MD = (
    "## M1b — LONG FORMS RE-USED AFTER THEIR FIRST USE (rule M1(k))\n\n"
    "| acronym | context | file:line | long form as written | excerpt |\n"
    "|---|---|---|---|---|\n"
    "| — | — | — | — | no long-form re-use detected |\n")

tmp8 = scratch("nbt_gate8_")
errs8 = []
np.check_review_contract(ctx, *fake_review_sandbox(tmp8, M1B_EMPTY_MD, [], coverage_m1()),
                         errs8, [])
check("E14 the sweep's 'no long-form re-use detected' row is not an instance",
      getattr(np, "m1b_row_count", lambda _t: -1)(M1B_EMPTY_MD) == 0 and not errs8,
      f"errs={str(errs8)[:160]}")

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
    sys.exit(1)
print("ALL ACRONYM LONG-FORM CHECKS PASSED")

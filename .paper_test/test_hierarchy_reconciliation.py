#!/usr/bin/env python3
"""M30 — the source-hierarchy reconciliation (submission vs code vs raw data).

Run:  python3 .paper_test/test_hierarchy_reconciliation.py

The hierarchy (github code > data in raw_data/ > main figures > ... >
supplementary text) was only a RESOLUTION rule: it decided which side wins once
two sources already disagreed. Its DETECTION side had no enumerating check, so
a written number, sample size, parameter or label that the shipped code or raw
data contradicts was found only when a human happened to compare the two. This
suite pins the fix:

  * `paper_docx_format.table_column_stats` describes every shipped table column
    (its own row count, min/max/mean/sum) -- the producer side of a row;
  * `paper_docx_format.hierarchy_seed_rows` pairs every written number the
    shipped tables do NOT prove with its candidate producer column(s) and states
    the check the code can make (a cohort-size sentence against the table's own
    row count), while skipping display-item labels and already-proved values;
  * `paper_docx_format.code_literal_rows` extracts the module-level literals of
    code/config files (`N_SAMPLES = 15`, `"threshold": 0.05`) as the producer
    side of a Methods parameter, skipping scratch and bookkeeping;
  * `code_side_evidence` carries both families and `seed_evidence_pack` seeds
    `M30_hierarchy_reconciliation.md` (two tables, disposition columns) for the
    review/audit/stage layouts and under `review/artifacts/` for the review; the
    quality layer reports an undisposed row;
  * the review contract requires the M30 coverage row and the artifact;
  * all five working prompts carry their M30 block (the review enumerates, the
    auditor attacks the old closures, the reviser aligns the written side under
    rule E12/rule C, the rewrite/integrate surface it) and the judge states the
    class is scoreable correctness/completeness -- with the frozen coverage map
    unchanged;
  * `sweeps.md`, `discovery.md` (proposals start at M31) and `edit_rules.md`
    (rule E12) carry the skill-side text, and the standalone prompt appendices
    stay byte-identical to them;
  * a stub review round passes its strict-artifact postcheck with the M30
    artifact present.

`PAPER_WS` retargets the suite at another copy of the tree.
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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nb = _load("paper_m30", WS / "paper_pipeline.py")
fmt = _load("paper_m30_fmt", WS / "paper_docx_format.py")

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


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


TABLES = [("raw_data/calls.csv", "sample,coverage\n1,31\n2,29\n3,30\n")]


def sample_corpus(dirp: Path) -> None:
    dirp.mkdir(parents=True, exist_ok=True)
    (dirp / "raw_data").mkdir(exist_ok=True)
    (dirp / "code").mkdir(exist_ok=True)
    (dirp / "manuscript.md").write_text(
        "Abstract\n\nWe analysed 12 samples and report accuracy 0.81.\n\n"
        "Methods\n\nWe used tool A with parameter 5.\n\n"
        "Results\n\nThe mean coverage was 30x.\n\n"
        "Figure 1 | Accuracy of the caller.\n",
        encoding="utf-8")
    (dirp / "raw_data" / "calls.csv").write_text(TABLES[0][1], encoding="utf-8")
    (dirp / "code" / "analysis.py").write_text("N_SAMPLES = 15\nPARAM = 7\n", encoding="utf-8")


def cli(*argv, timeout=900):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------------------
# 1. the code-side seed
# ---------------------------------------------------------------------------


def test_table_column_stats():
    print()
    print("== table_column_stats describes the producer side ==")
    stats = fmt.table_column_stats(TABLES)
    coverage = [s for s in stats if s["column"] == "coverage"][0]
    check("a column reports its own row count", coverage["n rows"] == 3, str(coverage)[:120])
    check("a column reports min/max/mean/sum",
          coverage["min"] == "29" and coverage["max"] == "31"
          and coverage["mean"] == "30" and coverage["sum"] == "90", str(coverage)[:160])
    check("a non-numeric column still reports its size",
          [s for s in stats if s["column"] == "sample"][0]["n rows"] == 3)
    check("a file with fewer than 3 lines is not a table",
          fmt.table_column_stats([("x.csv", "a,b\n1,2\n")]) == [])


def test_hierarchy_seed_rows():
    print()
    print("== hierarchy_seed_rows pairs written values with candidate producers ==")
    numbers = fmt.number_ledger(["We analysed 12 samples and report accuracy 0.81.",
                                 "Figure 1 | Accuracy of the caller."])
    for r in numbers:
        r["kind"] = "abstract" if r["document_paragraph"] == 0 else "legend"
        r["document"] = "manuscript.md"
    rows = fmt.hierarchy_seed_rows(numbers, TABLES)
    by_number = {r["number"]: r for r in rows}
    check("a cohort-size sentence is paired with the table's ID column",
          by_number["12"]["candidate producer"] == "raw_data/calls.csv:sample"
          and "3 data row(s)" in by_number["12"]["seed check"],
          str(by_number.get("12"))[:200])
    check("the written value is compared with the producer's own row count",
          "the sentence reads 12" in by_number["12"]["seed check"]
          and "-- reconcile" in by_number["12"]["seed check"])
    check("a value with no matching column gets an explicit 'look in code/raw_data' row",
          "code/ or raw_data/" in by_number["0.81"]["seed check"],
          str(by_number.get("0.81"))[:160])
    check("a display-item label is NOT a producer row",
          "1" not in by_number, str(sorted(by_number)))
    # a value a shipped table proves is not re-seeded
    proved = fmt.number_ledger(["The mean coverage was 30."])
    for r in proved:
        r["kind"] = "body"
    fmt.reconcile_number_rows(proved, TABLES)
    check("a value a shipped table PROVES is not seeded",
          proved[0].get("source") and fmt.hierarchy_seed_rows(proved, TABLES) == [])


def test_code_literal_rows():
    print()
    print("== code_literal_rows extracts the code's own constants ==")
    tmp = scratch("paper_m30_code_")
    (tmp / "analysis.py").write_text("import os\nN_SAMPLES = 15\nPARAM = 7\nx = 3\n", encoding="utf-8")
    (tmp / "config.yml").write_text("threshold: 0.05\nname: run\n", encoding="utf-8")
    (tmp / "revision_report.json").write_text('{"n": 15}\n', encoding="utf-8")
    (tmp / "work").mkdir()
    (tmp / "work" / "scratch.py").write_text("SEED = 42\n", encoding="utf-8")
    rows = fmt.code_literal_rows([(tmp, "", ())],
                                 skip_name=lambda n: n.lower() == "revision_report.json")
    symbols = {r["symbol"]: r["value"] for r in rows}
    check("ALL_CAPS constants are extracted", symbols.get("N_SAMPLES") == "15", str(symbols))
    check("hinted lowercase constants are extracted", symbols.get("PARAM") == "7")
    check("config-style literals are extracted", symbols.get("threshold") == "0.05")
    check("scratch under work/ is skipped", "SEED" not in symbols, str(symbols))
    check("a caller-declared bookkeeping file is skipped",
          "n" not in symbols, str(symbols))
    check("an un-hinted local variable is not a claim", "x" not in symbols)


# ---------------------------------------------------------------------------
# 2. the evidence pack and the seeded ledger
# ---------------------------------------------------------------------------


def test_evidence_and_seeding():
    print()
    print("== the pack carries M30 and seeds the ledger ==")
    tmp = scratch("paper_m30_ev_")
    corpus = tmp / "corpus"
    sample_corpus(corpus)
    ctx = type("C", (), {"cfg": {}})()
    ev = nb.code_side_evidence(ctx, corpus, "scratch:m30")
    check("CODE_SCANS carries the hierarchy family",
          (ev.get("hierarchy") or {}).get("rows") and
          any(r.get("number") == "12" for r in ev["hierarchy"]["rows"]),
          str((ev.get("hierarchy") or {}).get("count")))
    check("CODE_SCANS carries the code literals family",
          (ev.get("code_literals") or {}).get("count") == 2,
          str((ev.get("code_literals") or {}).get("rows"))[:160])
    check("the evidence summary names the M30 rows",
          "M30 hierarchy rows" in nb.evidence_pack_summary(ev))
    for where, sub in (("review", "review"), ("audit", ""), ("stage", "")):
        sb = tmp / f"run_{where}"
        sb.mkdir()
        nb.seed_evidence_pack(ctx, sb, corpus, where)
        work = (sb / sub / "work") if sub else (sb / "work")
        ledger = work / "M30_hierarchy_reconciliation.md"
        text = ledger.read_text(encoding="utf-8") if ledger.is_file() else ""
        check(f"{where}: work/M30_hierarchy_reconciliation.md is seeded", ledger.is_file())
        check(f"{where}: the ledger carries both tables and a disposition column",
              "## A. written values with candidate producers" in text
              and "## B. code/config literals" in text
              and text.count("| disposition |") == 2, text[:120])
    art = tmp / "run_review" / "review" / "artifacts" / "M30_hierarchy_reconciliation.md"
    check("the review's artifacts/ copy is seeded (the decision table)",
          art.is_file() and "seed check" in art.read_text(encoding="utf-8"))
    check("the review decision-artifact list includes the ledger",
          "artifacts/M30_hierarchy_reconciliation.md" in nb.DECISION_ARTIFACTS)
    check("the disposition mandate names the ledger",
          "M30_hierarchy_reconciliation" in nb.DISPOSITION_MANDATE)


def test_undisposed_row_is_a_problem():
    print()
    print("== an undisposed M30 row is a decision-artifact problem ==")
    tmp = scratch("paper_m30_quality_")
    art = tmp / "review" / "artifacts"
    art.mkdir(parents=True)
    (art / "M30_hierarchy_reconciliation.md").write_text(
        "# M30\n\n## A\n\n| # | document | kind | number | unit | sentence | candidate producer | "
        "producer summary | seed check | disposition |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        "| 1 | ms.md | abstract | 12 | | We analysed 12 samples. | raw_data/x.csv:sample | "
        "3 row(s) | differs |  |\n", encoding="utf-8")
    report = nb.artifact_quality_report(tmp / "review")
    check("the undisposed ledger row is reported",
          "artifacts/M30_hierarchy_reconciliation.md" in report, str(report)[:200])


# ---------------------------------------------------------------------------
# 3. the review contract
# ---------------------------------------------------------------------------


def test_review_contract():
    print()
    print("== the review contract requires the M30 coverage row and artifact ==")
    tmp = scratch("paper_m30_contract_")
    sb = tmp / "r1_review"
    (sb / "base").mkdir(parents=True)
    art = sb / "review" / "artifacts"
    art.mkdir(parents=True)
    (art / "M1_acronyms.md").write_text("| row |\n|---|\n", encoding="utf-8")
    ids = ([f"M{i}" for i in range(1, 18)] + ["M18", "M19", "M20", "M21", "M22", "M23",
                                              "M24", "M25", "M26", "M27", "M28", "M29"]
           + [f"J{i}" for i in range(1, 6)])
    fj = {"submission_dir": "base",
          "coverage": [{"check": c, "disposition": "clean -- basis: x"} for c in ids]}
    errs = []
    nb.check_review_contract(None, sb, fj, errs, [])
    check("the missing M30 coverage row is reported",
          any("'M30'" in e for e in errs), str(errs)[:200])
    check("the missing M30 artifact is reported",
          any("M30_hierarchy_reconciliation.md" in e for e in errs), str(errs)[:200])
    for fname in ("M25_artwork_parity.md", "M26_conventions.md", "M27_evidence_coverage.md",
                  "M28_symmetry.md", "M29_caption_schema.md",
                  "M30_hierarchy_reconciliation.md"):
        (art / fname).write_text("| row | disposition |\n|---|---|\n| x | OK |\n",
                                 encoding="utf-8")
    (sb / "review" / "ARCHITECTURE.md").write_text(
        "| document | section | paragraphs | current structure | reader cost | "
        "proposed reorganization | class | severity | disposition |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| ms | all | 1 | x | none | none | writing | Minor | OK |\n", encoding="utf-8")
    fj["coverage"].append({"check": "M30", "disposition": "clean -- basis: M30 artifact"})
    errs2 = []
    nb.check_review_contract(None, sb, fj, errs2, [])
    check("with the row and the artifact the contract passes", errs2 == [], str(errs2)[:200])


# ---------------------------------------------------------------------------
# 4. the prompts, the skills and the end-to-end path
# ---------------------------------------------------------------------------


def prompts() -> dict:
    P = Path("/tmp/x")
    return {
        "review": nb.review_prompt(P, "r1_review", 1),
        "audit": nb.audit_prompt(P, "r1_audit", 1),
        "rewrite": nb.rewrite_prompt(P, "r1_w1", 1, index=1, total=2),
        "revise": nb.revise_prompt(P, "r1_a2_revise", 1),
        "integrate": nb.integrate_prompt(P, "r1_i1", 1, self_id="a1", other_ids=["w1"]),
        "judge": nb.judge_prompt(P, "judge_tok_j1", 1, "tok", 1, 1, ["v1"]),
    }


def test_prompts():
    print()
    print("== the prompts carry their M30 block ==")
    P = prompts()
    flat = {role: " ".join(t.split()) for role, t in P.items()}
    for role, text in P.items():
        check(f"{role}: names M30", "M30" in text)
        check(f"{role}: has no unresolved token",
              "@@" not in text.replace("@@", "", 0) or "SOURCE_HIERARCHY@@" not in text)
    check("the review enumerates written-vs-producer pairs and the seeded artifact",
          "M30_hierarchy_reconciliation.md" in P["review"]
          and "SEED" not in P["review"].split("M30", 1)[0][-20:]
          and "could pair" in flat["review"])
    check("the review names the authority rule and the 'never fix the code here' guard",
          "github code > data in raw_data/" in flat["review"]
          and "NEVER \"fix\" the code here" in flat["review"])
    check("the review records a producer that is not in the corpus as `unable`",
          "the producer is not in the corpus" in flat["review"])
    check("the auditor attacks the old closures",
          "the code/raw data is out of scope" in flat["audit"]
          and "raw_data/ is read-only" in flat["audit"]
          and "github code > data in raw_data/" in flat["audit"])
    check("the reviser resolves under rule E12 with rule C for a code fix",
          "rule E12" in flat["revise"] and "rule C owns the fix" in flat["revise"]
          and "raw_data/ is READ-ONLY" in flat["revise"])
    check("the rewrite surfaces rather than resolves",
          "PROBLEMS SURFACED" in flat["rewrite"] and "never edit the code" in flat["rewrite"])
    check("the integrator aligns to the authoritative side",
          "authoritative artifact" in flat["integrate"] and "raw_data/ is never edited"
          in flat["integrate"])
    check("the judge states the class is scoreable, with the frozen map unchanged",
          "SOURCE-HIERARCHY DIFFERENCES ARE SCOREABLE" in flat["judge"]
          and "correctness" in flat["judge"]
          and "M30" in flat["judge"])
    expected_judge = set(nb.JUDGE_COVERAGE_CHECKS)
    check("the judge's frozen coverage map still excludes M30",
          "M30" not in expected_judge and "M25" not in expected_judge)


def test_skill_docs():
    print()
    print("== the skill references carry M30 and rule E12 ==")
    sweeps = (WS / "paper-skills" / "paper-review" / "references" / "sweeps.md").read_text(
        encoding="utf-8")
    discovery = (WS / "paper-skills" / "paper-review" / "references" / "discovery.md").read_text(
        encoding="utf-8")
    rules = (WS / "paper-skills" / "paper-revise" / "references" / "edit_rules.md").read_text(
        encoding="utf-8")
    check("sweeps.md defines M30 with purpose/enumeration/artifact/finding rules",
          "## M30 — Source-hierarchy reconciliation" in sweeps
          and "**Artifact.** `review/artifacts/M30_hierarchy_reconciliation.md`" in sweeps
          and "one finding per incompatible instance" in sweeps)
    check("sweeps.md carries the hierarchy and the seeded tables",
          "github code > data in raw_data/" in sweeps
          and "candidate producer column" in sweeps)
    check("sweeps.md's finding format and coverage table admit M30",
          "check: <M1–M30|J1–J5>" in sweeps and "M1–M30 and" in sweeps)
    check("discovery proposals now start at M31",
          "Proposals therefore start at M31" in " ".join(discovery.split())
          and "35 check IDs (M1–M30, J1–J5)" in discovery)
    check("edit_rules.md defines E12 (align the written side, rule C for code, raw_data read-only)",
          "## E12 — Source-hierarchy findings (M30)" in rules
          and "raw_data/` is READ-ONLY by contract" in rules
          and "rule C owns the fix" in rules)
    ip = (WS / "paper-skills" / "prompts" / "identify_issues.prompt.md").read_text(
        encoding="utf-8")
    ap = (WS / "paper-skills" / "prompts" / "adress_issues.prompt.md").read_text(
        encoding="utf-8")
    check("the standalone review prompt carries the M30 sweep (appendix sync)",
          "## M30 — Source-hierarchy reconciliation" in ip
          and "Proposals therefore start at M31" in " ".join(ip.split()))
    check("the standalone revise prompt carries rule E12 (appendix sync)",
          "## E12 — Source-hierarchy findings (M30)" in ap)


def test_stub_review_round():
    print()
    print("== a stub review round passes its strict-artifact postcheck with M30 ==")
    tmp = scratch("paper_m30_e2e_")
    src = tmp / "src"
    sample_corpus(src)
    root = tmp / "root"
    setup = cli("setup", "--source", str(src), "--root", str(root), "--rounds", "1",
                "--rewrites", "1", "--revises", "1", "--judges", "1", "--zotero", "off",
                "--placeholder-lookup", "off")
    check("setup succeeds", setup.returncode == 0, (setup.stdout + setup.stderr)[-200:])
    run = cli("run", "--root", str(root), "--only", "review",
              "--agent-cmd", json.dumps([sys.executable, str(WS / ".paper_test" / "stub_agent.py")]),
              "--retries", "0")
    # `--only review` deliberately leaves the ROUND incomplete (exit 3); the
    # evidence is the run record: the review finished and its postcheck passed
    # under the default strict-artifact policy.
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = (state.get("runs") or {}).get("r1_review") or {}
    check("the review run completes under the default strict-artifact policy",
          rec.get("status") == "done" and (rec.get("postcheck") or {}).get("ok") is True,
          json.dumps(rec.get("postcheck") or rec)[:300])
    sb = root / "runs" / "r1_review"
    art = sb / "review" / "artifacts" / "M30_hierarchy_reconciliation.md"
    check("the run's M30 artifact exists and is disposed",
          art.is_file() and "| disposition |" in art.read_text(encoding="utf-8"))
    seeded = sb / "review" / "work" / "M30_hierarchy_reconciliation.md"
    check("the seeded working copy carries the machine-found rows",
          seeded.is_file() and "raw_data/calls.csv" in seeded.read_text(encoding="utf-8"),
          seeded.read_text(encoding="utf-8")[:120] if seeded.is_file() else "missing")


def main() -> int:
    sections = (("tables", test_table_column_stats),
                ("seed", test_hierarchy_seed_rows),
                ("code", test_code_literal_rows),
                ("evidence", test_evidence_and_seeding),
                ("quality", test_undisposed_row_is_a_problem),
                ("contract", test_review_contract),
                ("prompts", test_prompts),
                ("skills", test_skill_docs),
                ("e2e", test_stub_review_round))
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL SOURCE-HIERARCHY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

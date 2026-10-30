#!/usr/bin/env python3
"""Opaque identifiers are FACTS: no replacement without independent evidence.

Run:  python3 .paper_test/test_identifier_correction_policy_2026_1027.py

The same over-correction that invented an e-mail domain can invent a DOI, an
accession, an ORCID, a UUID/UID, a git commit, a grant number, a registry id or
a domain-specific identifier. The pipeline now:

* states the rule in every stage prompt (shared D10 + the package hand-off
  block) and the revise skill;
* lets ANY independent evidence stand: the exact value already in the read-only
  corpus (another submission document, raw_data, the analysis code), a
  web-search result, a public registry, Crossref/DataCite/ORCID or a repository
  commit page, recorded in `work/FACT_VERIFICATION.json`;
* FAILS a replacement, shortening or renumbering with no such evidence;
* leaves the value byte-identical and requires a high-priority manual TODO row
  carrying `suggested: <value> (unverified)` when in doubt;
* allows a pure ADDITION for new content (a new reference's DOI) and warns when
  a new value closely resembles an existing one.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS: list[str] = []
TMPDIRS: list[Path] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def make_pkg(tmp: Path, name: str, text: str, suffix: str = ".md") -> Path:
    d = tmp / name
    d.mkdir(parents=True)
    (d / f"paper{suffix}").write_text(text, encoding="utf-8")
    return d


def make_docx(path: Path, text: str, split: bool = False) -> None:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    if split and len(text) > 12:
        cut = len(text) // 2
        runs = (f'<w:r><w:t>{text[:cut]}</w:t></w:r>'
                f'<w:r><w:t>{text[cut:]}</w:t></w:r>')
    else:
        runs = f'<w:r><w:t>{text}</w:t></w:r>'
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
           f'<w:document xmlns:w="{w}"><w:body><w:p>{runs}</w:p></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def gate(pp, base: Path, revised: Path, evidence=(), record=None):
    if record is not None:
        (revised / "work").mkdir(exist_ok=True)
        (revised / "work" / "FACT_VERIFICATION.json").write_text(
            json.dumps(record), encoding="utf-8")
    return pp.fact_token_change_problems(
        [(base, "", ())], [(revised, "", ("work",))], revised, "revise",
        evidence_sources=list(evidence))


def record(kind: str, before: str, after: str, *,
           url="https://www.ut.ee/en/people/mart-kask", query="verify identifier",
           date="2026-10-27", evidence=None, **extra) -> dict:
    return {"verifications": [dict({
        "kind": kind, "before": before, "after": after, "query": query,
        "source_url": url, "checked_at": date,
        "evidence": evidence or f"verified record: {after}",
    }, **extra)]}


CASES = (
    ("doi", "10.1000/abc123", "10.1000/def456", "DOI"),
    ("orcid", "0000-0002-1825-0097", "0000-0002-1825-0098", "ORCID"),
    ("uuid", "123e4567-e89b-12d3-a456-426614174000",
     "123e4567-e89b-12d3-a456-426614174001", "UUID"),
    ("accession", "GSE12345", "GSE12346", "ACCESSION"),
    ("commit", "1234567abcdef", "1234568abcdef", "GIT COMMIT"),
    ("grant", "R01 GM123456", "R01 GM123457", "FUNDING/GRANT"),
    ("uid", "ABC-12345", "ABC-12346", "UID"),
    ("domain", "A549", "A550", "DOMAIN-SPECIFIC"),
)


def line_for(kind: str, value: str) -> str:
    return {
        "doi": f"DOI: {value}\n",
        "orcid": f"ORCID: {value}\n",
        "uuid": f"UUID: {value}\n",
        "accession": f"Accession: {value}\n",
        "commit": f"commit {value}\n",
        "grant": f"Grant {value}\n",
        "uid": f"UID: {value}\n",
        "domain": f"Cell line: {value}\n",
    }[kind]


def test_policy_text():
    print("\n== the prompt and skill policy ==")
    p02 = (WS / "paper_pipeline_parts" / "p02_journal_modes.py").read_text(encoding="utf-8")
    p03 = (WS / "paper_pipeline_parts" / "p03_prompts.py").read_text(encoding="utf-8")
    check("the shared rules carry D10", "D10. AN OPAQUE IDENTIFIER" in p02)
    check("the hand-off block carries the sensitive-fact rule",
          "SENSITIVE_FACT_RULE" in p02 and "FACT_VERIFICATION.json" in p02)
    check("all three author-to-complete modes insert the rule",
          p02.count("\n@@SENSITIVE_FACT_RULE@@\n") == 3)
    check("the prompt states the manual TODO and unverified suggestion",
          "suggested: <value> (unverified)" in p02
          and "manual TODO" in p02)
    check("the revision audit names the opaque-fact rule",
          "DOI" in p03 and "work/FACT_VERIFICATION.json" in p03)
    check("the bounded repair names the opaque-fact rule",
          "revised/work/FACT_VERIFICATION.json" in p03)
    for rel in ("paper-skills/paper-revise/references/edit_rules.md",
                "paper-skills/prompts/adress_issues.prompt.md",
                "paper-skills/paper-revise/SKILL.md",
                "paper-skills/paper-review/references/sweeps.md",
                "paper-skills/prompts/identify_issues.prompt.md"):
        text = (WS / rel).read_text(encoding="utf-8")
        check(f"{rel}: carries the opaque-identifier evidence rule",
              "FACT_VERIFICATION.json" in text
              and (("OPAQUE IDENTIFIER" in text) or ("Opaque-identifier" in text)))
        check(f"{rel}: requires the suggested unverified value in the manual TODO",
              "suggested:" in text or "manual TODO" in text)

    pp = load("identifier_policy_prompts", WS / "paper_pipeline.py")
    P = Path("/tmp/x")
    prompts = {
        "review": pp.review_prompt(P, "r1_guided_review", 1),
        "audit": pp.audit_prompt(P, "r1_audit", 1),
        "rewrite": pp.rewrite_prompt(P, "r1_w1", 1, index=1, total=2),
        "revise": pp.revise_prompt(P, "r1_a2_revise", 1),
        "integrate": pp.integrate_prompt(P, "r1_i1", 1, self_id="a1", other_ids=["w1"]),
        "judge": pp.judge_prompt(P, "judge_tok_j1", 1, "tok", 1, 1, ["v1"]),
    }
    for role, text in prompts.items():
        check(f"{role} prompt carries D10", "D10. AN OPAQUE IDENTIFIER" in text)
        check(f"{role} prompt leaves no unresolved token", "@@" not in text)
    for role in ("review", "audit", "rewrite", "revise", "integrate"):
        check(f"{role} prompt carries the sensitive-fact block and record",
              "SENSITIVE_FACT_RULE" not in prompts[role]   # the token is replaced
              and "FACT_VERIFICATION.json" in prompts[role]
              and "OPAQUE IDENTIFIERS" in prompts[role])
    for mode in ("document", "readme", "off"):
        text = pp.placeholder_rule_text(mode)
        check(f"{mode} mode carries the sensitive-fact block",
              "OPAQUE IDENTIFIERS" in text and "FACT_VERIFICATION.json" in text)
    repair = pp.revision_repair_prompt(P, "r1_a2_revise", 1, 2)
    check("the repair prompt carries the generalized evidence rule",
          "FACT_VERIFICATION.json" in repair and "suggested:" in repair)


def test_gate():
    print("\n== identifier replacement gate ==")
    pp = load("identifier_policy_gate", WS / "paper_pipeline.py")
    tmp = scratch("identifier_policy_")
    for kind, old, new, label in CASES:
        base = make_pkg(tmp, f"{kind}_base", line_for(kind, old))
        same = make_pkg(tmp, f"{kind}_same", line_for(kind, old))
        errs, warns = gate(pp, base, same)
        check(f"{kind}: unchanged value passes", not errs and not warns, f"{errs} {warns}")

        bad = make_pkg(tmp, f"{kind}_bad", line_for(kind, new))
        errs, _ = gate(pp, base, bad)
        check(f"{kind}: unverified replacement FAILS with a manual-TODO instruction",
              any(label in e and "manual TODO" in e and "suggested:" in e for e in errs),
              str(errs))

        good = make_pkg(tmp, f"{kind}_good", line_for(kind, new))
        errs, warns = gate(pp, base, good, record=record(kind, old, new))
        check(f"{kind}: an independent recorded lookup allows the exact replacement",
              not errs and not warns, f"{errs} {warns}")

    gene_base = make_pkg(tmp, "gene_base", "Gene: ENSG00000141510\n")
    gene_bad = make_pkg(tmp, "gene_bad", "Gene: ENSG00000141511\n")
    errs, _ = gate(pp, gene_base, gene_bad)
    check("a domain-specific gene identifier is gated too",
          any("DOMAIN-SPECIFIC ID" in e for e in errs), str(errs))
    gene_good = make_pkg(tmp, "gene_good", "Gene: ENSG00000141511\n")
    errs, warns = gate(pp, gene_base, gene_good,
                       record=record("domain", "ENSG00000141510", "ENSG00000141511"))
    check("a verified gene identifier replacement passes",
          not errs and not warns, f"{errs} {warns}")

    base = make_pkg(tmp, "doi_base_evidence", line_for("doi", "10.1000/abc123"))
    evidence_dir = tmp / "raw_data"
    evidence_dir.mkdir()
    (evidence_dir / "ids.csv").write_text(
        "kind,value\ndoi,10.1000/def456\n", encoding="utf-8")
    good = make_pkg(tmp, "doi_evidence", line_for("doi", "10.1000/def456"))
    errs, warns = gate(pp, base, good, evidence=[(evidence_dir, "", ())])
    check("the exact value in read-only raw data is independent evidence",
          not errs and not warns, f"{errs} {warns}")

    addition = make_pkg(tmp, "doi_addition",
                        line_for("doi", "10.1000/abc123")
                        + line_for("doi", "10.1000/newref999"))
    errs, warns = gate(pp, base, addition)
    check("a pure new-reference DOI addition is not a correction",
          not errs and not warns, f"{errs} {warns}")

    acc_base = make_pkg(tmp, "acc_base", line_for("accession", "GSE12345"))
    acc_add = make_pkg(tmp, "acc_add",
                       line_for("accession", "GSE12345")
                       + line_for("accession", "GSE12346"))
    errs, warns = gate(pp, acc_base, acc_add)
    check("a similar new accession is reported as a possible correction, not a failure",
          not errs and any("resembles" in w for w in warns), f"{errs} {warns}")

    bad = make_pkg(tmp, "doi_bad_record", line_for("doi", "10.1000/def456"))
    errs, _ = gate(pp, base, bad,
                   record=record("doi", "10.1000/abc123", "10.1000/def456",
                                 url="https://example.org/doi"))
    check("a reserved/example source URL is not independent evidence",
          any("reserved/example host" in e for e in errs), str(errs))

    wrong_kind = make_pkg(tmp, "doi_wrong_kind", line_for("doi", "10.1000/def456"))
    errs, _ = gate(pp, base, wrong_kind,
                   record=record("orcid", "10.1000/abc123", "10.1000/def456"))
    check("a record whose kind does not match the value is rejected",
          any("does not match the declared kind" in e for e in errs), str(errs))

    removal = make_pkg(tmp, "doi_removed", "No identifier here.\n")
    errs, warns = gate(pp, base, removal)
    check("removing an identifier is recorded, not silently accepted",
          not errs and any("no longer carries DOI" in w for w in warns), f"{errs} {warns}")

    email_base = make_pkg(tmp, "email_base", "Contact: a@x.edu\n")
    email_after = make_pkg(tmp, "email_after", "Contact: b@x.edu\n")
    errs, warns = gate(pp, email_base, email_after)
    check("the general identifier gate does not duplicate the e-mail gate",
          not errs and not warns, f"{errs} {warns}")


def test_docx():
    print("\n== DOCX identifiers are joined before matching ==")
    pp = load("identifier_policy_docx", WS / "paper_pipeline.py")
    tmp = scratch("identifier_policy_docx_")
    base = tmp / "base"
    revised = tmp / "revised"
    base.mkdir()
    revised.mkdir()
    make_docx(base / "main.docx", "DOI 10.1000/abc123", split=True)
    make_docx(revised / "main.docx", "DOI 10.1000/def456", split=True)
    errs, _ = gate(pp, base, revised)
    check("a DOCX DOI split across runs is detected", bool(errs), str(errs))
    check("the error names the DOI", any("DOI" in e for e in errs), str(errs))


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_policy_text()
        test_gate()
        test_docx()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL IDENTIFIER-CORRECTION POLICY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

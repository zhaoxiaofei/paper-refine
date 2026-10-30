#!/usr/bin/env python3
"""E-mail addresses are contact FACTS, never inferable typos.

Run:  python3 .paper_test/test_email_address_policy_2026_1027.py

The observed over-correction was `mart.ksk@ut.ee` -> `mart.kask@helsinki.fi`:
the local part was fixed, but the domain was inferred from the printed
affiliation and the reviewer's own note admitted it could not verify the real
address. The pipeline now:

* states the rule in every stage prompt and the revise skill: an address may
  change only to a string the input corpus already carries verbatim, or to
  one a recorded web-search result verifies (`work/EMAIL_VERIFICATION.json`:
  query, source URL, checked date and a verbatim quote containing the exact
  address); otherwise it stays byte-identical and the mismatch is a
  high-priority author query;
* runs a deterministic gate in every package-producing postcheck: a NEW
  address without an in-corpus match or a matching verification row FAILS the
  stage; a removed non-placeholder address is recorded; a case-only change is
  not a change; and the DOCX extraction joins runs before matching.
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
EMAIL_RULE = "E-MAIL ADDRESSES ARE NOT INFERABLE TYPOS"
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
    if split:
        runs = (f'<w:r><w:t>{text.split("@", 1)[0]}@</w:t></w:r>'
                f'<w:r><w:t>{text.split("@", 1)[1]}</w:t></w:r>')
    else:
        runs = f'<w:r><w:t>{text}</w:t></w:r>'
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
           f'<w:document xmlns:w="{w}"><w:body><w:p>{runs}</w:p></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def gate(pp, base: Path, revised: Path, evidence=(), record=None):
    if record is not None:
        (revised / "work").mkdir(exist_ok=True)
        (revised / "work" / "EMAIL_VERIFICATION.json").write_text(
            json.dumps(record), encoding="utf-8")
    return pp.email_address_change_problems(
        [(base, "", ())], [(revised, "", ("work",))], revised, "revise",
        evidence_sources=list(evidence))


def record(before: str, after: str, *, url="https://www.ut.ee/en/people/mart-kask",
           query="author contact address", date="2026-10-27",
           evidence=None, **extra) -> dict:
    return {"verifications": [dict({
        "before": before, "after": after, "query": query, "source_url": url,
        "checked_at": date,
        "evidence": evidence or f"Corresponding author: {after}",
    }, **extra)]}


def test_policy_text():
    print("\n== the prompt and skill policy ==")
    p02 = (WS / "paper_pipeline_parts" / "p02_journal_modes.py").read_text(encoding="utf-8")
    p03 = (WS / "paper_pipeline_parts" / "p03_prompts.py").read_text(encoding="utf-8")
    check("no stage prompt calls a standard domain a correction basis",
          "standard email domain" not in p02 and "a standard domain" not in p03)
    check("the shared decision rules carry the contact-fact rule",
          "D9. AN E-MAIL ADDRESS IS A CONTACT FACT" in p02)
    check("the hand-off rule carries the e-mail block", EMAIL_RULE in p02)
    check("the revision audit treats an e-mail edit as a new defect",
          "An E-MAIL ADDRESS is NOT on" in p03
          and "work/EMAIL_VERIFICATION.json" in p03)
    check("all three author-to-complete modes insert it",
          p02.count("\n@@EMAIL_ADDRESS_RULE@@\n") == 3)
    for rel in ("paper-skills/paper-revise/references/edit_rules.md",
                "paper-skills/prompts/adress_issues.prompt.md",
                "paper-skills/paper-revise/SKILL.md",
                "paper-skills/paper-review/references/sweeps.md",
                "paper-skills/prompts/identify_issues.prompt.md"):
        text = (WS / rel).read_text(encoding="utf-8")
        check(f"{rel}: carries the e-mail rule", EMAIL_RULE in text
              or "contact FACT" in text)
        check(f"{rel}: drops the standard-domain basis",
              "standard email domain" not in text)
    sweeps = (WS / "paper-skills/paper-review/references/sweeps.md").read_text(encoding="utf-8")
    flat = " ".join(sweeps.split())
    check("the review sweep says never propose a replacement address",
          "never propose a replacement address" in flat
          and "never infer a domain from the affiliation" in flat)

    pp = load("email_policy_prompts", WS / "paper_pipeline.py")
    P = Path("/tmp/x")
    prompts = {
        "review": pp.review_prompt(P, "r1_targeted_review", 1),
        "audit": pp.audit_prompt(P, "r1_audit", 1),
        "rewrite": pp.rewrite_prompt(P, "r1_w1", 1, index=1, total=2),
        "revise": pp.revise_prompt(P, "r1_a2_revise", 1),
        "integrate": pp.integrate_prompt(P, "r1_i1", 1, self_id="a1", other_ids=["w1"]),
        "judge": pp.judge_prompt(P, "judge_tok_j1", 1, "tok", 1, 1, ["v1"]),
    }
    for role, text in prompts.items():
        check(f"{role} prompt carries the shared D9 rule",
              "D9. AN E-MAIL ADDRESS IS A CONTACT FACT" in text)
        check(f"{role} prompt leaves no unresolved token", "@@" not in text)
    for role in ("review", "audit", "rewrite", "revise", "integrate"):
        check(f"{role} prompt carries the e-mail block and its record",
              EMAIL_RULE in prompts[role]
              and "work/EMAIL_VERIFICATION.json" in prompts[role])
    for mode in ("document", "readme", "off"):
        text = pp.placeholder_rule_text(mode)
        check(f"{mode} mode carries the e-mail block", EMAIL_RULE in text)
        check(f"{mode} mode names the verification record",
              "work/EMAIL_VERIFICATION.json" in text)
    revision_audit = pp.revision_audit_prompt(P, "r1_a2_revise", 1)
    check("the revision-audit prompt carries the contact-fact rule",
          "An E-MAIL ADDRESS is NOT on" in revision_audit
          and "work/EMAIL_VERIFICATION.json" in revision_audit)


def test_gate():
    print("\n== the package gate ==")
    pp = load("email_policy_gate", WS / "paper_pipeline.py")
    tmp = scratch("email_policy_")
    base = make_pkg(tmp, "base", "Contact: mart.ksk@ut.ee\n")
    same = make_pkg(tmp, "same", "Contact: mart.ksk@ut.ee\n")
    errs, warns = gate(pp, base, same)
    check("an unchanged address passes", not errs and not warns, f"{errs} {warns}")

    fabricated = make_pkg(tmp, "fabricated", "Contact: mart.kask@helsinki.fi\n")
    errs, warns = gate(pp, base, fabricated)
    check("an inferred new domain FAILS the stage",
          any("CONTACT FACT" in e and "mart.kask@helsinki.fi" in e for e in errs), str(errs))
    check("the replaced address is also recorded as removed",
          any("no longer carries" in w for w in warns), str(warns))

    local_only = make_pkg(tmp, "local_only", "Contact: mart.kask@ut.ee\n")
    errs, _ = gate(pp, base, local_only)
    check("a local-part change is an address change and needs evidence",
          any("mart.kask@ut.ee" in e and "CONTACT FACT" in e for e in errs), str(errs))

    verified = make_pkg(tmp, "verified", "Contact: mart.kask@ut.ee\n")
    errs, warns = gate(pp, base, verified,
                       record=record("mart.ksk@ut.ee", "mart.kask@ut.ee"))
    check("a recorded web-search verification allows the exact correction",
          not errs and not warns, f"{errs} {warns}")

    partial = make_pkg(tmp, "partial", "Contact: mart.ksk@ut.ee\n"
                                        "Correspondence: mart.kask@ut.ee\n")
    errs, warns = gate(pp, base, partial,
                       record=record("mart.ksk@ut.ee", "mart.kask@ut.ee"))
    check("a verified correction warns when the superseded address is left behind",
          not errs and any("superseded address" in w for w in warns), f"{errs} {warns}")

    bad = make_pkg(tmp, "bad_record", "Contact: mart.kask@ut.ee\n")
    errs, _ = gate(pp, base, bad,
                   record=record("mart.ksk@ut.ee", "mart.kask@ut.ee",
                                 evidence="a page with no address on it"))
    check("a record whose evidence does not contain the address is rejected",
          any("evidence" in e for e in errs), str(errs))

    bad_url = make_pkg(tmp, "bad_url", "Contact: mart.kask@ut.ee\n")
    errs, _ = gate(pp, base, bad_url,
                   record=record("mart.ksk@ut.ee", "mart.kask@ut.ee",
                                 url="example.org/people"))
    check("a record without an http(s) source is rejected",
          any("source_url" in e for e in errs), str(errs))

    placeholder_url = make_pkg(tmp, "placeholder_url", "Contact: mart.kask@ut.ee\n")
    errs, _ = gate(pp, base, placeholder_url,
                   record=record("mart.ksk@ut.ee", "mart.kask@ut.ee",
                                 url="https://example.org/people"))
    check("a record on a reserved/example host is not a web-search result",
          any("reserved/example host" in e for e in errs), str(errs))

    evidence_dir = tmp / "raw_data"
    evidence_dir.mkdir()
    (evidence_dir / "contacts.csv").write_text(
        "name,email\nMart Kask,mart.kask@ut.ee\n", encoding="utf-8")
    in_corpus = make_pkg(tmp, "in_corpus", "Contact: mart.kask@ut.ee\n")
    errs, warns = gate(pp, base, in_corpus, evidence=[(evidence_dir, "", ())])
    check("an address the input corpus already carries needs no record",
          not errs, str(errs))

    case_base = make_pkg(tmp, "case_base", "Contact: mart.kask@ut.ee\n")
    case = make_pkg(tmp, "case", "Contact: Mart.Kask@UT.EE\n")
    errs, warns = gate(pp, case_base, case)
    check("a case-only rewrite is not an address change", not errs and not warns,
          f"{errs} {warns}")

    removed = make_pkg(tmp, "removed", "The authors thank the editors.\n")
    errs, warns = gate(pp, base, removed)
    check("removing a real address is recorded, not silently accepted",
          not errs and any("no longer carries" in w for w in warns), f"{errs} {warns}")

    placeholder_base = make_pkg(tmp, "placeholder_base", "Contact: x@example.edu\n")
    placeholder_removed = make_pkg(tmp, "placeholder_removed", "No contact shown.\n")
    errs, warns = gate(pp, placeholder_base, placeholder_removed)
    check("removing a reserved/example address is not a real-contact deletion",
          not errs and not warns, f"{errs} {warns}")


def test_docx_runs():
    print("\n== DOCX text is joined before the address is matched ==")
    pp = load("email_policy_docx", WS / "paper_pipeline.py")
    tmp = scratch("email_policy_docx_")
    base = tmp / "base"
    revised = tmp / "revised"
    base.mkdir()
    revised.mkdir()
    make_docx(base / "main.docx", "mart.ksk@ut.ee", split=True)
    make_docx(revised / "main.docx", "mart.kask@helsinki.fi", split=True)
    errs, _ = gate(pp, base, revised)
    check("a DOCX address split across runs is detected", bool(errs), str(errs))
    check("the docx error names the fabricated address",
          any("mart.kask@helsinki.fi" in e for e in errs), str(errs))


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_policy_text()
        test_gate()
        test_docx_runs()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL E-MAIL ADDRESS POLICY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

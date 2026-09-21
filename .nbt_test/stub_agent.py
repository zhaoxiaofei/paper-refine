#!/usr/bin/env python3
"""Deterministic stub agent for the nbt_pipeline end-to-end validation."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def np_aux(path: Path) -> bool:
    """Mirror the pipeline's auxiliary-name rule for this stub."""
    n = path.name.lower()
    return n.endswith((".tracked.docx", ".before-after.docx"))


def digest_tree(d: Path) -> str:
    h = hashlib.sha256()
    if not d.is_dir():
        return ""
    for p in sorted(d.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(d).as_posix().encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def copy_corpus(src: Path, dst: Path, increment_tokens: bool, extra_line: str = ""):
    """Copy a package; `increment_tokens=True` simulates the LEGACY rename
    convention (a suffix letter/digit bumped one step). Real agents no longer
    increment version tokens -- basenames are kept -- but the pipeline still
    tolerates legacy increments, and these fixtures keep that path covered."""
    dst.mkdir(parents=True, exist_ok=True)

    def target_name(name: str) -> str:
        if not increment_tokens:
            return name
        stem, suffix = Path(name).stem, Path(name).suffix
        m = re.match(r"^(.*[-_])([A-Za-z])$", stem)
        if m:
            return f"{m.group(1)}{chr(ord(m.group(2)) + 1)}{suffix}"
        m = re.match(r"^(.*[-_]v?)(\d+)$", stem)
        if m:
            return f"{m.group(1)}{int(m.group(2)) + 1}{suffix}"
        return name

    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        new_rel = Path(*[target_name(part) for part in rel.parts])
        out = dst / new_rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix.lower() in (".md", ".txt", ".tex", ".bib") and extra_line:
            text = p.read_text(encoding="utf-8", errors="replace")
            out.write_text(text + extra_line, encoding="utf-8")
        else:
            shutil.copy2(p, out)


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def write_docx(p: Path, text: str) -> None:
    import zipfile
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    doc = (f'<?xml version="1.0" encoding="UTF-8"?><w:document {ns}><w:body>'
           f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)


def fill_seeded_tables(dirp: Path) -> None:
    """Fill the seeded decision tables the way the strict policy expects.

    The pipeline seeds one row per code-side finding with EMPTY disposition
    cells and an OUTLINE whose `summary` cells are empty. `--strict-artifacts`
    (on by default now) fails a run whose tables are left that way -- one
    blanket sentence across many rows is the exact failure the policy exists
    for -- so the stub fills each row with a RULE-SPECIFIC (here: rule-naming,
    row-numbered) reason, and writes generated OUTLINE summaries that are not
    echoes of the first sentence.
    """
    if not dirp.is_dir():
        return
    for p in sorted(dirp.glob("*.md")):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        head_i = next((i for i, l in enumerate(lines) if l.strip().startswith("|")), None)
        if head_i is None:
            continue
        header = [c.strip().lower() for c in lines[head_i].strip("|").split("|")]

        def cell(cells, key, default=""):
            i = header.index(key) if key in header else None
            return cells[i] if i is not None and i < len(cells) else default

        filled, changed_any = list(lines), False
        for j in range(head_i + 1, len(lines)):
            line = lines[j]
            if not line.strip().startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if len(cells) < len(header):
                cells += [""] * (len(header) - len(cells))
            row_no = j - head_i
            rule = cell(cells, "rule")
            reason = (f"OK — {rule or 'row ' + str(row_no)}: reviewed against its own bar "
                      f"({p.stem} row {row_no})")
            changed = False
            for i, key in enumerate(header):
                if i >= len(cells):
                    break
                if key in ("disposition", "resolution") and not cells[i]:
                    cells[i] = reason
                    changed = True
                elif key == "summary" and not cells[i]:
                    heading = cell(cells, "heading") or "the section"
                    cells[i] = f"stub summary {row_no}: the paragraph's claim under {heading}"
                    changed = True
                elif key in ("decision", "authoritative term") and not cells[i]:
                    cells[i] = f"stub decision {row_no}: one meaning, used consistently"
                    changed = True
            if changed:
                filled[j] = "| " + " | ".join(cells) + " |"
                changed_any = True
        if changed_any:
            p.write_text("\n".join(filled) + "\n", encoding="utf-8")


def do_review(sb: Path, name: str, round_no: int) -> int:
    out = sb / "review"
    (out / "artifacts").mkdir(parents=True, exist_ok=True)
    (out / "round2").mkdir(parents=True, exist_ok=True)
    findings = [{"id": "F-001", "location": "base/manuscript-o.md",
                 "category": 0, "check": "M1", "severity": "Minor",
                 "evidence": "stub", "explanation": "stub",
                 "status": "resolvable"}]
    nid = 2
    prior = sb / "prior_round" / "findings.json"
    if prior.is_file():
        pj = json.loads(prior.read_text(encoding="utf-8"))
        for pf in pj.get("findings") or []:
            findings.append({"id": f"F-{nid:03d}", "location": str(pf.get("location") or "base"),
                             "category": int(pf.get("category") or 0),
                             "check": str(pf.get("check") or "M1"),
                             "severity": str(pf.get("severity") or "Minor"),
                             "evidence": str(pf.get("evidence") or ""),
                             "explanation": f"carried over from {pf.get('id')} (stub re-check)",
                             "status": "resolvable"})
            nid += 1
    write_json(out / "findings.json", {
        "submission_dir": "./base", "guidelines_source": "stub",
        "findings": findings,
        "artifacts": {"M1_acronyms": []},
        "coverage": ([{"check": c, "disposition": "clean -- basis: stub artifact", "detail": "stub"}
                      for c in [f"M{i}" for i in range(1, 18)] + [f"J{i}" for i in range(1, 5)]]
                     + [{"check": "M19",
                         "disposition": "0 findings -- abstract/main text within the relaxed caps",
                         "detail": "stub"}]
                     + [{"check": "M18",
                         "disposition": "legend lengths recorded (no cap configured in the stub)",
                         "detail": "stub"}]
                     + [{"check": "M20",
                         "disposition": "code-side formatting rows disposed: 0 findings",
                         "detail": "stub: review/work/FORMAT_SCAN.json audited"}]
                     + [{"check": c,
                         "disposition": f"clean -- basis: stub {c} artifact",
                         "detail": "stub"} for c in ("M21", "M22", "M23", "M24")])})
    (out / "findings.md").write_text("# findings (stub)\n\nsummary: stub\n", encoding="utf-8")
    (out / "artifacts" / "M1_acronyms.md").write_text("| row |\n|---|\n", encoding="utf-8")
    (out / "artifacts" / "M19_length.md").write_text(
        "# M19 (stub)\n\n| document | section | words | cap | disposition |\n|---|---|---|---|---|\n"
        "| base | abstract | 0 | 172 | OK |\n| base | main text | 0 | 3750 | OK |\n",
        encoding="utf-8")
    (out / "artifacts" / "VIS_visual.md").write_text(
        "# visual inspection (stub)\n\nstub: no renderer used; pages reviewed: none\n",
        encoding="utf-8")
    write_json(out / "round2" / "findings_extra.json", {"findings": [], "coverage": []})
    (out / "round2" / "findings_extra.md").write_text("# extra (stub)\n", encoding="utf-8")
    (out / "round2" / "new_sweeps.md").write_text("# none\n", encoding="utf-8")
    fill_seeded_tables(out / "artifacts")
    write_json(sb / "_pipeline_done.json", {
        "stage": "review", "run_id": name, "round": round_no, "status": "complete",
        "error": None, "summary": {"findings_total": 1, "critical_found": 0,
                                   "major_found": 0, "minor_found": 1}})
    return 0


def do_audit(sb: Path, name: str, round_no: int) -> int:
    """Deterministic auditor: confirm every frozen finding, add nothing.

    The stub mirrors a *conservative* auditor (the one the pipeline always
    accepts): every frozen id is confirmed with a reason, no drop is claimed, so
    the audited list equals the frozen list. The interesting behaviour (drops
    with evidence, promoted `AU-` findings) is exercised by the unit fixtures of
    `test_residual_audit_2026_0921.py`, not by the stub round.
    """
    rev = sb / "review"
    frozen = []
    fj = rev / "findings.json"
    if fj.is_file():
        try:
            frozen = ((json.loads(fj.read_text(encoding="utf-8")) or {})
                      .get("findings") or [])
        except (OSError, ValueError):
            frozen = []
    out = sb / "audit"
    out.mkdir(parents=True, exist_ok=True)
    disps = [{"id": str(f.get("id")), "verdict": "confirm",
              "reason": "stub auditor: the quoted text exists at the stated location",
              "evidence": str(f.get("evidence") or "stub evidence")[:80],
              "severity_after": str(f.get("severity") or "Minor")}
             for f in frozen if f.get("id")]
    write_json(out / "audit.json",
               {"round": round_no, "dispositions": disps, "adds": [],
                "counts": {"confirmed": len(disps), "dropped": 0, "added": 0},
                "coverage": [{"check": "M20",
                              "disposition": "stub: the seeded formatting rows were audited"}],
                "notes": "stub auditor: every frozen finding confirmed"})
    (out / "AUDIT.md").write_text(
        "# audit (stub)\n\nEvery frozen finding was confirmed; nothing was dropped.\n",
        encoding="utf-8")
    (out / "DISPOSITION_AUDIT.md").write_text(
        "| rule | row | reviewer's reason | verdict | finding |\n|---|---|---|---|---|\n",
        encoding="utf-8")
    write_json(sb / "_pipeline_done.json",
               {"stage": "audit", "run_id": name, "round": round_no, "status": "complete",
                "error": None,
                "summary": {"findings_total": len(disps), "confirmed": len(disps),
                            "dropped": 0, "added": 0, "finding_tier_rows_examined": 0,
                            "promoted": 0}})
    return 0


def do_revision(sb: Path, name: str, round_no: int, stage: str) -> int:
    base = sb / ("base" if stage == "revise" else "self")
    out = sb / "revised"
    copy_corpus(base, out, increment_tokens=True,
                extra_line=f"\n<!-- stub edit for {name} -->\n")
    (out / "MANUAL_STEPS.md").write_text(
        "- Verify the accession number [AUTHOR TO COMPLETE: accession number]\n",
        encoding="utf-8")
    (out / "CHANGELOG.md").write_text("# changelog (stub)\n", encoding="utf-8")
    (out / "REVISION_REPORT.md").write_text("# report (stub)\n", encoding="utf-8")
    language_pass_artifact(out, "revised documents")
    # The ledger contract: one row per finding id from the frozen review (the
    # revise stage consumes review/findings.json; the cross stage works from the
    # self/ package, which carries the same ledger back in). A run that lists no
    # row at all cannot prove "no finding was silently dropped" and is retried.
    rows = []
    for rel in ("review/findings.json", "revised/revision_report.json"):
        p = sb / rel
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found = doc.get("findings") if isinstance(doc, dict) else doc
        for row in (found or []):
            if not isinstance(row, dict):
                continue
            fid = row.get("id")
            if fid and not any(r.get("id") == fid for r in rows):
                rows.append({"id": fid, "verdict": "fixed",
                             "rationale": "stub revision applied",
                             "evidence": "chromium-free stub edit marker in the document"})
    write_json(out / "revision_report.json",
               rows or [{"id": "F-000", "verdict": "none",
                         "rationale": "stub: the frozen review listed no finding",
                         "evidence": "n/a"}])
    write_docx(out / "manuscript-p.tracked.docx", "tracked changes auxiliary")
    # visual pass: render the first docx to PDF/PNG when a renderer exists
    vis = out / "VISUAL_CHECK.md"
    docx = sorted(out.glob("*.docx"))
    docx = [d for d in docx if not np_aux(d)] if docx else []
    lines = ["# visual inspection (stub)", ""]
    if docx and shutil.which("pandoc"):
        pdf = docx[0].with_suffix(".pdf")
        r = subprocess.run(["pandoc", str(docx[0]), "-o", str(pdf)], capture_output=True, text=True)
        png = []
        if r.returncode == 0 and pdf.is_file() and shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-r", "60", "-png", "-f", "1", "-l", "1", str(pdf),
                            str(out / "vis")], capture_output=True, text=True)
            png = sorted(out.glob("vis*.png"))
        lines += [f"- renderer: pandoc (content-level; direct Word formatting is dropped)",
                  f"- file: {docx[0].name}; rendered images: {[p.name for p in png]}",
                  "- findings: none (stub)"]
        if pdf.is_file():
            pdf.unlink()
        for p in png:
            p.unlink()
    else:
        lines += ["- no renderer available in this stub run; pages NOT visually verified (stub)"]
    vis.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if stage == "cross":
        (out / "DIFF_LEDGER.md").write_text("# ledger (stub)\n", encoding="utf-8")
    summary = ({"findings_total": 1, "fixed": 1, "critical_remaining": 0,
                "writing_remaining": 0, "manual_items": 1}
               if stage == "revise" else
               {"ported": 1, "kept_base": 0, "ignored_cosmetic": 0, "shared_defects_left": 0,
                "critical_remaining": 0, "writing_remaining": 0, "manual_items": 1})
    write_json(sb / "_pipeline_done.json", {"stage": stage, "run_id": name,
                                            "round": round_no, "status": "complete",
                                            "error": None, "summary": summary})
    return 0


def language_pass_artifact(out: Path, label: str) -> None:
    """The L1-L11 language-pass artifact every package-producing stage owes.

    One change row plus one COVERAGE row per step (a step that changed nothing
    still gets a row), which is what the postcheck parses.
    """
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    lines = ["# language pass (stub) — L1-L11", "",
             "| step | location | before | after | reason |",
             "|---|---|---|---|---|",
             f"| L9 | {label} | stub: stiff phrasing | stub: smoother phrasing | stub row |",
             "", "## coverage", "",
             "| step | rows changed | note |", "|---|---|---|"]
    for i in range(1, 12):
        lines.append(f"| L{i} | {'1' if i == 9 else '0'} | stub: no further change needed |")
    (work / "R6_language.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def do_rewrite(sb: Path, name: str, round_no: int, prompt: str = "") -> int:
    """The rewrite arm: a full candidate in rewritten/ from the round's base."""
    out = sb / "rewritten"
    copy_corpus(sb / "base", out, increment_tokens=True,
                extra_line=f"\n<!-- stub rewrite for {name} -->\n")
    m = re.search(r"THIS ARM'S LEVEL:\s*(STRUCTURAL|SENTENCE)", prompt or "", re.I)
    level = (m.group(1).lower() if m else "structural")
    other = "sentence" if level == "structural" else "structural"
    (out / "REWRITE_REPORT.md").write_text(
        "# rewrite report (stub)\n\n"
        f"Level: {level}\n\n"
        "## ORGANIZATION MAP\n- stub: one move, for testing\n"
        f"## DELIBERATELY UNCHANGED\n- stub: the science\n"
        f"- stub: the {other}-level work belongs to the other candidate of this round\n"
        "## PROBLEMS SURFACED\n- stub: none\n"
        "## WHAT THE REWRITE INTENTIONALLY LEFT BROKEN\n- stub: none\n",
        encoding="utf-8")
    language_pass_artifact(out, "rewritten documents")
    (out / "MANUAL_STEPS.md").write_text("- (stub) none\n", encoding="utf-8")
    (out / "CHANGELOG.md").write_text("# changelog (stub rewrite)\n", encoding="utf-8")
    (out / "VISUAL_CHECK.md").write_text(
        "# visual inspection (stub rewrite)\n\n"
        "- no renderer used by this stub; pages NOT visually verified (stub)\n",
        encoding="utf-8")
    write_json(sb / "_pipeline_done.json", {
        "stage": "rewrite", "run_id": name, "round": round_no, "status": "complete",
        "error": None,
        "summary": {"reorganized_sections": 1, "problems_surfaced": 0,
                    "critical_remaining": 0, "writing_remaining": 0, "manual_items": 0}})
    return 0


def do_integration(sb: Path, name: str, round_no: int) -> int:
    """The integration arm: self/ reworked with the WHOLE pool as donors."""
    out = sb / "integrated"
    copy_corpus(sb / "self", out, increment_tokens=True,
                extra_line=f"\n<!-- stub edit for {name} -->\n")
    donor_ids = sorted(p.name for p in (sb / "others").iterdir() if p.is_dir()) \
        if (sb / "others").is_dir() else []
    # The ledger contract: one row per difference with its own artifact, its
    # size class (both classes, because the pool carries both rewrite levels)
    # and its effect on the frozen findings.
    diffs = out / "work" / "diffs"
    diffs.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, d in enumerate(donor_ids, 1):
        size = "large" if i % 2 == 1 else "small"
        art = f"integrated/work/diffs/D-{i:03d}.md"
        (diffs / f"D-{i:03d}.md").write_text(
            f"# D-{i:03d} ({size}, donor {d})\n\n"
            + ("## outline diff\n- self: (stub outline)\n- donor: (stub outline)\n"
               "- merged: (stub outline)\n" if size == "large"
               else "## before/after\n- self: (stub sentence)\n- donor: (stub sentence)\n"
                    "- shipped: (stub sentence)\n"),
            encoding="utf-8")
        rows.append(f"| D-{i:03d} | {d} | (e) | {size} | stub: donor wording | "
                    f"stub: self wording | keep-self | stub: no ported difference | "
                    f"none | {art} | none |")
    (out / "DIFF_LEDGER.md").write_text(
        "# diff ledger (stub integration)\n\n"
        "| id | donor | location | size | donor says | self says | verdict | why | "
        "effect | artifact | finding effect |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        + "\n".join(rows) + "\n", encoding="utf-8")
    language_pass_artifact(out, "integrated documents")
    (out / "MANUAL_STEPS.md").write_text(
        "- (stub) none\n", encoding="utf-8")
    (out / "CHANGELOG.md").write_text("# changelog (stub integration)\n", encoding="utf-8")
    (out / "VISUAL_CHECK.md").write_text(
        "# visual inspection (stub integration)\n\n"
        "- no renderer used by this stub; pages NOT visually verified (stub)\n",
        encoding="utf-8")
    write_json(sb / "_pipeline_done.json", {
        "stage": "integrate", "run_id": name, "round": round_no, "status": "complete",
        "error": None,
        "summary": {"ported": 0, "kept_base": 0, "ignored_cosmetic": 0,
                    "shared_defects_left": len(donor_ids), "donors_read": len(donor_ids),
                    "critical_remaining": 0, "writing_remaining": 0, "manual_items": 0}})
    return 0


def stub_basis(score: int) -> dict:
    """The graded basis (judge contract v2) for a deterministic stub score.

    The stub judges a whole-tree digest, so the ledger can only cite the
    digest ordering; the tier/severity below is what the score allows (a
    |score| <= 2 never needs a MAJOR/CRITICAL item outside formatting, but a
    non-zero score always needs an item on its own side).
    """
    if score > 0:
        return {"basis": "consistency",
                "resolved": [{"check": "M1", "tier": "consistency", "severity": "minor",
                              "evidence": "stub: target digest sorts ahead of the opponent"}],
                "introduced": []}
    if score < 0:
        return {"basis": "consistency", "resolved": [],
                "introduced": [{"check": "M1", "tier": "consistency", "severity": "minor",
                                "evidence": "stub: opponent digest sorts ahead of the target"}]}
    return {"basis": "none", "resolved": [], "introduced": []}


JUDGE_CHECK_IDS = ([f"M{i}" for i in range(1, 18)]
                   + ["M18", "M19", "M20", "M21", "M22", "M23", "M24"]
                   + [f"J{i}" for i in range(1, 5)])


def stub_checks(score: int) -> dict:
    """Contract v3 per-opponent coverage map (every frozen check id disposed)."""
    out = {c: "clean -- stub: deterministic digest comparison" for c in JUDGE_CHECK_IDS}
    if score:
        out["M1"] = "findings -- stub: digest ordering (see resolved/introduced)"
    return out


def do_judge(sb: Path, name: str, round_no: int, prompt: str) -> int:
    token = re.search(r'"target_id":\s*"([^"]+)"', prompt).group(1)
    jidx = int(re.search(r'"judge_index":\s*(\d+)', prompt).group(1))
    labels = re.findall(r"no more, no fewer:\s*(.+)", prompt)[0].strip()
    labels = [x.strip() for x in labels.split(",")]
    tdig = digest_tree(sb / "target")
    comps = []
    for lab in labels:
        odig = digest_tree(sb / "field" / lab)
        score = 0 if tdig == odig else (1 if tdig > odig else -1)
        comps.append({"opponent_label": lab, "score": score,
                      "reason": "stub deterministic comparison",
                      "checks": stub_checks(score), **stub_basis(score)})
    # No "round": a judge session is never told which round it belongs to (the
    # run id is an opaque token), so the sheet cannot carry one.
    write_json(sb / "scores.json", {"run_id": name, "target_id": token,
                                    "judge_index": jidx, "comparisons": comps,
                                    "notes": "stub"})
    jr = sb / "judge_review"
    (jr / "artifacts").mkdir(parents=True, exist_ok=True)
    (jr / "inventory.md").write_text("# inventory (stub)\n", encoding="utf-8")
    (jr / "artifacts" / "M1_acronyms.md").write_text("| row |\n|---|\n", encoding="utf-8")
    (jr / "artifacts" / "VIS_visual.md").write_text(
        "# visual inspection (stub)\n\nstub: pages reviewed: none\n", encoding="utf-8")
    write_json(sb / "_pipeline_done.json", {"stage": "judge", "run_id": name,
                                            "status": "complete", "error": None})
    return 0


def main() -> int:
    sb = Path.cwd()
    prompt = (sb / "PROMPT.md").read_text(encoding="utf-8")
    name = sb.name
    m = re.search(r"r(\d+)_", name)
    round_no = int(m.group(1)) if m else 1
    if name.endswith("_review"):
        return do_review(sb, name, round_no)
    if name.endswith("_audit"):
        return do_audit(sb, name, round_no)
    if re.search(r"_w\d+$", name):
        return do_rewrite(sb, name, round_no, prompt)
    if re.search(r"_a\d+_revise$", name):
        return do_revision(sb, name, round_no, "revise")
    if re.search(r"_i\d+$", name):
        return do_integration(sb, name, round_no)
    # A judge run id is an OPAQUE token ("judge_<token>_j<k>"): it carries no
    # round or arm, so match on its own prefix.
    if "_judge_" in name or name.startswith("judge_"):
        return do_judge(sb, name, round_no, prompt)
    print(f"stub: unknown sandbox {sb}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

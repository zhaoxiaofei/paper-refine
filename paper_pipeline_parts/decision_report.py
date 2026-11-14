"""Formatting for the decision report's run metadata and integrity summary."""


def header_lines(*, generated, root, version, config_line, venue_lines, certification,
                 verdict, clean_readme_name, integrity, pin_count, problems):
    """Render the report heading and integrity section from prepared data."""
    L = []
    L.append("# Round Pipeline — Decision Report")
    L.append("")
    L.append(f"Generated: {generated}  |  pipeline root: `{root}`  |  orchestrator v{version}")
    L.append(config_line)
    for line in venue_lines:
        L.append(f"- {line}")
    if certification:
        _cert = certification
        _verdict = verdict
        _why = _cert.get("blockers") or _cert.get("notes")
        if isinstance(_why, str):
            # A hand-built/legacy record may carry ONE note as a bare string;
            # iterating it would join its characters ("n; o; t; e").
            _why = [_why]
        if not _why:
            # "every gate passed" is a CERTIFIED verdict, never a fallback for a
            # provisional/not-certified one with no recorded reason.
            if _cert.get("certified"):
                _why = ["every gate passed"]
            elif _cert.get("provisional") or _cert.get("auto_promoted"):
                _why = ["no blockers were recorded, but the answer is provisional, not a "
                        "certified panel result"]
            else:
                _why = ["no blockers were recorded, but the decision is not certified"]
        L.append("")
        L.append(f"**Certification: {_verdict}.** " + "; ".join(str(x) for x in _why))
        _cv = _cert.get("clean_version") or {}
        if _cv.get("published"):
            L.append(f"- final_clean_version/: published by this decision "
                     f"({_cv.get('status') or _verdict.lower()}); status in "
                     f"`{_cv.get('readme') or clean_readme_name}`")
        else:
            L.append(f"- final_clean_version/: NOT (re)built by this decision"
                     + (f" -- {_cv['skipped_reason']}" if _cv.get("skipped_reason") else "")
                     + f" (status still recorded in `{clean_readme_name}`)")
    L.append("")
    L.append("## 0. Integrity")
    L.append("")
    L.append(f"- pristine original: {'ok' if integrity['pristine_ok'] else 'CHANGED'} "
             f"({integrity['pristine_detail']})")
    L.append(f"- pinned champion chain: {'ok' if not integrity['pinned_errors'] else 'CHANGED'} "
             f"({pin_count} pinned version(s))")
    for e in integrity["pinned_errors"]:
        L.append(f"  - {e}")
    if integrity.get("evidence_not_verifiable"):
        L.append(f"- evidence NOT verifiable for {len(integrity['evidence_not_verifiable'])} "
                 f"run(s): their sandboxes are missing (pruned or removed by hand), so the "
                 f"decision rests on the recorded manifests alone")
        for e in integrity["evidence_not_verifiable"][:8]:
            L.append(f"  - {e}")
    if integrity.get("recovery"):
        L.append(f"- orchestrator RECOVERY: {len(integrity['recovery'])} run(s) dropped base "
                 f"file(s) that were restored mechanically (advisory; the judged package is "
                 f"complete, and this never changes a score)")
        for rec in integrity["recovery"][:8]:
            L.append(f"  - {rec['run']} ({rec['version']}): {rec['count']} restored file(s)"
                     + (f", e.g. {', '.join(rec['files'][:3])}" if rec.get("files") else ""))
    if integrity.get("visual_not_verified"):
        L.append(f"- visual verification INCOMPLETE in {len(integrity['visual_not_verified'])} "
                 f"run(s) (a renderer was unavailable or the agent recorded 'not visually "
                 f"verified'); the author must complete those pages: "
                 + ", ".join(integrity["visual_not_verified"][:8]))
    if problems:
        L.append("")
        L.append("**Problems found while recomputing the decision (the stored chain is NOT "
                 "re-derived silently):**")
        L.append("")
        for p in problems:
            L.append(f"- {p}")
    L.append("")
    return L

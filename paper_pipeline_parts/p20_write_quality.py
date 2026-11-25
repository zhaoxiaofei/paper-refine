# Part 20/21 of the pipeline -- executed by the loader in its own globals.
# Mandatory independent quality gates for non-revision LLM authors.
#
# Revision arms use the existing, separately enforced revision-audit chain.
# The executor wrapper covers normal, resumed, conform and add-venue sessions;
# auxiliary read/report and bounded-repair sessions never recurse through it.
# This part is frozen with the rest of paper_pipeline_parts at setup/sync-code.

WRITE_ARTIFACTS = {"response": "response", "template-rewrite": "out",
                   "add-venue": "store"}
WRITE_QUALITY_DIR = "write_quality"


def _write_manifest(root: Path) -> dict:
    """An exact regular-file inventory; links/special files cannot hide edits."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"not a regular artifact directory: {root}")
    files = {}
    for entry in sorted(root.rglob("*")):
        if entry.is_symlink() or not (entry.is_dir() or entry.is_file()):
            raise ValueError(f"link or special file in authoring artifact: {entry}")
        if entry.is_file():
            files[entry.relative_to(root).as_posix()] = sha256_file(entry)
    return files


def _write_digest(root: Path) -> str:
    return hashlib.sha256(json.dumps(_write_manifest(root), sort_keys=True).encode()).hexdigest()


def _write_owned_digest(root: Path) -> str:
    # Difference-tracking copies are deterministic orchestrator auxiliaries,
    # never the authored artifact, submitted corpus or a scored improvement.
    owned = {rel: digest for rel, digest in _write_manifest(root).items()
             if not _is_aux_doc(Path(rel).name)}
    return hashlib.sha256(json.dumps(owned, sort_keys=True).encode()).hexdigest()


def _write_copy(source: Path, destination: Path) -> None:
    _write_manifest(source)
    shutil.copytree(source, destination)


def _write_input_digest(root: Path) -> str:
    """Read-only pipeline inputs may contain the pipeline's evidence aliases.

    Inventory both link targets and their bytes, refuse cycles/special files,
    and materialize aliases as ordinary copies in independent sandboxes.
    Authored artifacts themselves still reject every symlink.
    """
    entries = {}

    def visit(path, rel, ancestors):
        if path.is_symlink():
            entries[rel + ":link"] = os.readlink(path)
        if path.is_dir():
            real = path.resolve()
            if real in ancestors:
                raise ValueError("cycle in read-only writer inputs")
            for child in sorted(path.iterdir()):
                visit(child, rel + "/" + child.name, ancestors | {real})
        elif path.is_file():
            entries[rel] = sha256_file(path)
        else:
            raise ValueError(f"unreadable/special writer input: {path}")

    visit(root, ".", set())
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def _write_read_json(path: Path):
    text = read_text_bounded(path)
    if text is None:
        raise ValueError(f"missing or unreadable {path.name}")
    return json.loads(text)


def _write_plan(path: Path, artifact: Path) -> list:
    data = _write_read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ValueError("audit must return an object with a rows list")
    # A failed/missing scientific prerequisite is not an empty, passing audit.
    if not isinstance(data.get("blocked", []), list):
        raise ValueError("audit blocked/manual items must be a list")
    if data.get("blocked") and not data["rows"]:
        raise ValueError("audit requires manual work: " + str(data.get("blocked"))[:400])
    seen = set()
    for row in data["rows"]:
        if not isinstance(row, dict):
            raise ValueError("audit row is not an object")
        if any(not isinstance(row.get(k), str) for k in
               ("id", "file", "location", "wrong", "correct", "basis", "edit", "evidence")):
            raise ValueError("incomplete audit row")
        rid, rel = row["id"], row["file"]
        if not rid.strip() or rid in seen or not rel.strip() or _unsafe_package_rel(rel):
            raise ValueError("duplicate audit id or unsafe artifact path")
        if "\\" in rel or strip_leading_dot_slash(rel) != rel:
            raise ValueError("audit paths must be canonical artifact-relative paths")
        if any(not row[k].strip() for k in ("location", "basis", "edit", "evidence")):
            raise ValueError("audit row has no deciding evidence or proposed edit")
        if not (row["wrong"].strip() or row["correct"].strip()):
            raise ValueError("audit row describes no locatable change")
        target = artifact / rel
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError("audit row must name one regular file")
        seen.add(rid)
    return data["rows"]


def _write_mandate(kind: str) -> str:
    return {
        "response": "Check every concern against the final manuscript, original feedback, "
                    "revision ledger and response map. Verify verbatim quotations, exact change "
                    "locations, truthful resolution claims and new-data citations. Repair ONLY "
                    "the response letter/map; never edit the manuscript or invent results.",
        "template-rewrite": "Check the source against the conformed package and the recorded "
                            "venue/template instructions: preserve scientific meaning, facts, "
                            "documents, figures, references and live fields. Check actual venue "
                            "compliance. Repair ONLY the conformed artifact; source/templates "
                            "and venue rules are immutable.",
        "add-venue": "Check the staged venue profile, README row and downloaded sources against "
                     "the writer's original instructions and authoritative journal evidence. "
                     "Do not invent venue requirements. Repair ONLY the staged artifact; never "
                     "modify the published venue store. Missing evidence is blocked/manual.",
        "revise": "Check the final revised package against base, findings, dispositions and "
                  "revision/repair ledgers. Verify fixes, factual preservation, edit scope and "
                  "introduced regressions. In major/minor modes stay inside admitted concerns "
                  "and regressions caused by their edits; do not conduct a general review."
    }[kind]


def _write_session(session: Path, parent: dict, cmd: list, timeout: int,
                   prompt: str, stage: str) -> dict:
    if not cmd:
        raise ValueError("an agent command is required for independent write verification")
    write_text_atomic(session / PROMPT_FILE, prompt)
    auxiliary = {"id": str(parent["id"]) + "_" + stage, "kind": stage,
                 "round": parent.get("round", 0), "status": "running",
                 "sandbox": str(session)}
    result = _execute_attempt_raw(session, auxiliary, _write_fresh_command(cmd), timeout)
    if result.get("error") or result.get("rc") != 0:
        raise ValueError(f"{stage} failed: {result.get('error') or result.get('rc')}")
    return {"id": auxiliary["id"], "command": auxiliary.get("agent_command"),
            "prompt_sha256": auxiliary.get("prompt_sha256"),
            "duration": result.get("dur"), "log": result.get("log")}


def _write_inputs(sb: Path, session: Path, output_rel: str) -> None:
    inputs = session / "inputs"
    inputs.mkdir()
    for entry in sorted(sb.iterdir()):
        if entry.name in (WRITE_QUALITY_DIR, output_rel) or entry.name.startswith("_"):
            continue
        if entry.is_dir():
            _write_input_digest(entry)
            shutil.copytree(entry, inputs / entry.name)
        elif entry.is_file():
            shutil.copy2(entry, inputs / entry.name)


def _write_audit(sb: Path, parent: dict, artifact: Path, cmd: list, timeout: int,
                 session: Path, stage: str) -> tuple:
    session.mkdir(parents=True)
    _write_copy(artifact, session / "artifact")
    _write_inputs(sb, session, WRITE_ARTIFACTS.get(parent["kind"], REVISED_DIR))
    before = (_write_digest(session / "artifact"), _write_digest(session / "inputs"))
    prompt = (
        "INDEPENDENT WRITE AUDITOR — a NEW read/report-only session.\n"
        f"Original writer role: {parent['kind']}. Stage: {stage}.\n"
        + _write_mandate(parent["kind"]) + "\n"
        "Read all of artifact/ and the relevant original mandate/evidence under inputs/. "
        "Neither directory may change. Write only AUDIT.json and optional AUDIT.md. "
        "Every confirmed repairable defect must have one row; no silently omitted defects. "
        "Use {\"rows\": [], \"blocked\": []} for a checked artifact needing no repairs. "
        "Each nonempty row has string fields id, file (relative to artifact/), location, "
        "wrong, correct, basis, edit, evidence. Quote the localized wrong/correct text "
        "where possible; an insertion has wrong=\"\", a deletion has correct=\"\". "
        "Record missing evidence, author decisions or unverifiable scientific repairs in "
        "blocked with their location and prerequisite; never manufacture a correction. "
        "Do not edit the artifact, inputs, parent sandbox or any published files. "
        "This is verification, not a writing or repair session.\n")
    metadata = _write_session(session, parent, cmd, timeout, prompt, stage)
    if before != (_write_digest(session / "artifact"), _write_digest(session / "inputs")):
        raise ValueError("independent auditor changed its read-only artifact or inputs")
    rows = _write_plan(session / "AUDIT.json", session / "artifact")
    metadata["blocked"] = _write_read_json(session / "AUDIT.json").get("blocked", [])
    return rows, metadata


def _write_repair_check(pre: Path, after: Path, rows: list, ledger_path: Path) -> None:
    data = _write_read_json(ledger_path)
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ValueError("repair ledger must have a rows list")
    plan = {r["id"]: r for r in rows}
    ledger = {}
    for item in data["rows"]:
        if not isinstance(item, dict) or item.get("id") not in plan or item["id"] in ledger:
            raise ValueError("unknown, duplicate or malformed repair ledger row")
        if item.get("verdict") not in ("confirmed", "rejected") or not str(item.get("reason") or "").strip():
            raise ValueError("every repair requires a revalidation verdict and evidence")
        if item["verdict"] == "confirmed" and any(not isinstance(item.get(k), str)
                                                   for k in ("before", "after")):
            raise ValueError("confirmed repairs require exact before/after quotes")
        ledger[item["id"]] = item
    if set(ledger) != set(plan):
        raise ValueError("repair did not revalidate every planned item")
    confirmed = [r for r in rows if ledger[r["id"]]["verdict"] == "confirmed"]
    allowed = {r["file"] for r in confirmed}
    old, new = _write_manifest(pre), _write_manifest(after)
    changed = {r for r in set(old) | set(new) if old.get(r) != new.get(r)}
    if changed - allowed:
        raise ValueError("bounded repair changed unplanned files: " + ", ".join(sorted(changed - allowed)))
    for rel in allowed:
        group = [r for r in confirmed if r["file"] == rel]
        if rel in old and rel not in new:
            raise ValueError("bounded repair removed an artifact file")
        quotes = [(ledger[r["id"]]["before"], ledger[r["id"]]["after"]) for r in group]
        if _repair_spans_cover(pre, after, rel, quotes):
            raise ValueError(f"repair changed text outside its confirmed quotes: {rel}")
        pairs = [(r["wrong"], r["correct"], r["location"]) for r in group
                 if r["wrong"] and r["correct"]]
        if pairs and _repair_plan_pairs_cover(pre, after, rel, pairs):
            raise ValueError(f"repair did not apply the described wrong/correct changes: {rel}")
        for r in group:
            item = ledger[r["id"]]
            for field, quote in (("wrong", "before"), ("correct", "after")):
                if r[field] and _repair_norm(r[field]) not in _repair_norm(item[quote]):
                    raise ValueError("repair quotes do not describe their planned correction")
            if old.get(rel) == new.get(rel) and r["wrong"] != r["correct"]:
                raise ValueError(f"confirmed repair was not applied: {r['id']}")


def audit_write_output(sb: Path, rec: dict, cmd: list, timeout: int,
                       output_rel: str = None, verify_only: bool = False) -> dict:
    """Audit exact bytes, repair only a plan, independently verify, then publish.

    Nothing is installed into the parent artifact on any failure. Auxiliary
    attempts are separate sessions and their metadata never replaces the
    author's prompt/session identity. An interrupted chain has no passing
    digest and therefore cannot be adopted as an accepted output.
    """
    output_rel = output_rel or WRITE_ARTIFACTS[rec["kind"]]
    artifact = sb / output_rel
    quality = sb / WRITE_QUALITY_DIR
    if quality.is_symlink():
        raise ValueError("write quality directory is a symlink")
    if quality.exists():
        shutil.rmtree(quality)
    quality.mkdir()
    result = {"status": "failed", "role": rec["kind"], "sessions": [], "repairs": 0}
    rec["write_quality"] = result
    try:
        original_digest = _write_digest(artifact)
        # Protect all original inputs and the parent's completion marker too.
        protected = {p.name: _write_input_digest(p)
                     for p in sb.iterdir() if p.name != WRITE_QUALITY_DIR}

        def unchanged():
            current = {p.name: _write_input_digest(p)
                       for p in sb.iterdir() if p.name != WRITE_QUALITY_DIR}
            if protected != current:
                raise ValueError("quality session changed the original writer sandbox")

        rows, metadata = _write_audit(sb, rec, artifact, cmd, timeout,
                                      quality / "audit", "write-audit")
        result["sessions"].append(metadata)
        blocked = metadata.get("blocked", [])
        unchanged()
        if rows and verify_only:
            raise ValueError("post-repair verification still finds defects; no second repair pass")
        if rows:
            repair = quality / "repair"
            repair.mkdir()
            _write_copy(artifact, repair / "artifact")
            _write_inputs(sb, repair, output_rel)
            write_json_atomic(repair / "PLAN.json", {"rows": rows})
            guard = (_write_digest(repair / "inputs"), sha256_file(repair / "PLAN.json"))
            prompt = (
                "BOUNDED WRITE REPAIR — one separate session, never a new authoring pass.\n"
                + _write_mandate(rec["kind"]) + "\n"
                "Read PLAN.json, artifact/ and inputs/. Re-open locations and independently "
                "reverify EVERY row using its evidence. Edit ONLY artifact/ and ONLY confirmed "
                "plan rows. Write LEDGER.json outside artifact/ with {\"rows\": [{\"id\": "
                "\"...\", \"verdict\": \"confirmed|rejected\", \"reason\": \"re-runnable evidence\", "
                "\"before\": \"exact applied quote\", \"after\": \"exact applied quote\"}]}. "
                "Include adjacent unchanged context in before/after quotes for insertions "
                "and deletions so the entire changed span, including separators, is covered. "
                "Account for each id exactly once. Reject unverifiable corrections with evidence; "
                "do not invent a replacement. Never edit inputs/, PLAN.json, parent files or "
                "any unplanned item. Do not conduct another review or repair loop.\n")
            result["sessions"].append(_write_session(repair, rec, cmd, timeout, prompt, "write-repair"))
            if guard != (_write_digest(repair / "inputs"), sha256_file(repair / "PLAN.json")):
                raise ValueError("bounded repair modified its immutable inputs/plan")
            unchanged()
            _write_repair_check(artifact, repair / "artifact", rows, repair / "LEDGER.json")
            residual, metadata = _write_audit(sb, rec, repair / "artifact", cmd, timeout,
                                              quality / "verification", "write-verification")
            result["sessions"].append(metadata)
            unchanged()
            if residual:
                raise ValueError("post-repair verification found unresolved defects; author action required")
            if blocked:
                raise ValueError("repairable items were bounded repaired, but author work remains: "
                                 + str(blocked)[:400])
            # Install only the independently verified, bounded result.
            backup = quality / "before"
            artifact.rename(backup)
            try:
                shutil.copytree(repair / "artifact", artifact)
            except BaseException:
                if artifact.exists():
                    shutil.rmtree(artifact)
                backup.rename(artifact)
                raise
            result["repairs"] = len(rows)
        result.update(status="done", artifact_digest=_write_owned_digest(artifact),
                      input_digests={p.name: _write_input_digest(p) for p in sb.iterdir()
                                     if p.name not in (WRITE_QUALITY_DIR, output_rel)
                                     and not p.name.startswith("_")},
                      audited_digest=original_digest, checked_at=utcnow())
    except (OSError, ValueError, TypeError) as exc:
        result["error"] = str(exc)
    write_json_atomic(quality / "RESULT.json", result)
    if result["status"] != "done":
        raise ValueError("mandatory independent write audit failed: " + result["error"])
    return result


def write_quality_problem(sb: Path, kind: str, rec: dict = None) -> str:
    """Require a passing audit of the exact current artifact, not a stale flag."""
    try:
        record = (rec.get("write_quality") or {}) if rec is not None else _write_read_json(
            sb / WRITE_QUALITY_DIR / "RESULT.json")
        if record.get("status") != "done" or record.get("role") != kind:
            return "mandatory independent write audit is incomplete"
        output = WRITE_ARTIFACTS.get(kind, REVISED_DIR)
        if record.get("artifact_digest") != _write_owned_digest(sb / output):
            return "mandatory independent write audit is stale: artifact bytes changed"
        inputs = record.get("input_digests")
        if not isinstance(inputs, dict):
            return "mandatory independent write audit has no input provenance"
        for name, digest in inputs.items():
            if _unsafe_package_rel(name) or "/" in name or "\\" in name:
                return "invalid independent write audit input path"
            if digest != _write_input_digest(sb / name):
                return "mandatory independent write audit is stale: writer inputs changed"
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return "mandatory independent write audit is missing/invalid: " + str(exc)
    return ""


def required_writer_problem(ctx, rec: dict) -> str:
    if rec.get("kind") not in ("revise", "response"):
        return ""
    sb = ctx.sandbox_of(rec)
    if rec.get("kind") == "revise":
        if (rec.get("revision_audit") or {}).get("status") != "done":
            return "mandatory independent revision audit is incomplete"
        if rec.get("revision_chain") != "complete":
            return "mandatory revision audit/repair/verification chain is incomplete"
        if not sb.exists():
            # Only the explicit prune operation may replace live byte checks
            # with its archived acceptance record. Arbitrary missing output or
            # a legacy skipped audit never qualifies.
            quality = rec.get("write_quality") or {}
            try:
                archived = _write_read_json(ctx.reports_dir / "write_quality" / f"{rec['id']}.json")
                if (quality.get("status") == "done" and quality.get("artifact_digest")
                        and rec.get("write_quality_pruned") == quality["artifact_digest"]
                        and archived == quality):
                    return ""
            except (OSError, ValueError, TypeError):
                pass
            return "missing revised artifact has no archived mandatory audit"
    return write_quality_problem(sb, rec["kind"], rec)


def ensure_conform_quality(sb: Path, args, verify_only: bool = False, command=None) -> None:
    problem = write_quality_problem(sb, "template-rewrite")
    if not problem:
        return
    agent = str(getattr(args, "agent", None) or DEFAULTS.get("agent", "codex"))
    if not command and agent == "manual" and not getattr(args, "agent_cmd", None):
        die("conform adoption blocked: " + problem +
            "; rerun conform with --agent/--agent-cmd for independent verification")
    rec = {"id": TEMPLATE_REWRITE_DIRNAME, "kind": "template-rewrite", "round": 0}
    try:
        audit_write_output(sb, rec, command or resolve_agent_cmd(agent, getattr(args, "agent_cmd", None)),
                           _timeout_seconds(args, DEFAULTS.get("timeout", 14400)),
                           verify_only=verify_only)
    except (OSError, ValueError, TypeError) as exc:
        die("conform adoption blocked: " + str(exc))


# One executor boundary covers automatic and resumed authoring sessions. A
# named auxiliary prompt is a bounded repair/read-only role, never a writer.


def _write_fresh_command(cmd: list) -> list:
    """A continuation of the author is never an independent auditor session."""
    fresh = list(cmd)
    if len(fresh) > 3 and fresh[1:3] == ["exec", "resume"]:
        del fresh[2:4]
    for flag in ("--session-id", "--resume"):
        while flag in fresh:
            at = fresh.index(flag)
            del fresh[at:at + 2]
    fresh = [arg for arg in fresh if arg != "--continue"]
    return fresh


def _execute_attempt_in(sb: Path, rec: dict, cmd: list, timeout: int,
                        prompt_name: str = PROMPT_FILE, log_name: str = "_agent.log",
                        archive_marker: bool = True) -> dict:
    author = rec.get("kind") in WRITE_ARTIFACTS and prompt_name in (PROMPT_FILE, RESUME_PROMPT_FILE)
    if author:
        rec.pop("write_quality", None)
        previous = sb / WRITE_QUALITY_DIR
        if previous.is_symlink():
            previous.unlink()
        elif previous.exists():
            shutil.rmtree(previous)
    result = _execute_attempt_raw(sb, rec, cmd, timeout, prompt_name, log_name, archive_marker)
    if author and result.get("rc") == 0 and not result.get("error"):
        try:
            audit_write_output(sb, rec, cmd, timeout)
        except (OSError, ValueError, TypeError) as exc:
            result.update(rc=1, error=str(exc), failure_kind="write_quality")
    return result


def ensure_decision_write_quality(ctx) -> None:
    """Certification cannot replay skipped, failed or stale authoring audits."""
    # Certification/adoption never treats an old skipped audit as a pass.
    missing_write_quality = []
    for run in ctx.runs():
        if run.get("status") == "done" and run.get("kind") in ("revise", "response"):
            problem = required_writer_problem(ctx, run)
            if problem:
                missing_write_quality.append(f"{run['id']}: {problem}")
    if missing_write_quality:
        die("decision blocked by mandatory post-write quality checks: "
            + "; ".join(missing_write_quality[:8]), code=5)


def conform_templates_for_source(ctx, source: Path) -> dict:
    """Use Word templates for Word submissions; preserve other source formats."""
    if any(p.suffix.lower() == ".docx" and not is_non_manuscript_rel(
            p.relative_to(source).as_posix()) for p in template_package_files(source)):
        return venue_word_templates(ctx)
    return {}


def conform_document_names(source: Path) -> list:
    return [p.relative_to(source).as_posix() for p in template_package_files(source)
            if p.suffix.lower() in (".docx", ".md", ".txt", ".tex", ".ltx", ".rst")
            and not is_non_manuscript_rel(p.relative_to(source).as_posix())]


def guideline_conform_postcheck(sb: Path, source: Path, policy=None) -> dict:
    """Guideline conformance for non-Word packages, with explicit content parity.

    Layout/preamble changes are declared in the existing replacement ledger;
    the independent conform auditor verifies the actual venue rules and meaning.
    Read-only evidence, analysis code, figures and other non-prose files remain
    byte-identical. Original file names and the complete package are preserved.
    """
    out = sb / "out"
    errors, warnings = [], []
    checked = covered = 0
    before, after = Counter(), Counter()
    documents = []
    ledger = out / "REPLACEMENT_LEDGER.md"
    exceptions, ledger_errors = _template_ledger_exceptions(ledger)
    if not ledger.is_file():
        errors.append("out/REPLACEMENT_LEDGER.md is missing")
    errors.extend(ledger_errors)
    source_files = template_package_files(source)
    names = {p.relative_to(source).as_posix() for p in source_files}
    text_exts = {".md", ".txt", ".tex", ".ltx", ".rst"}
    for original in source_files:
        rel = original.relative_to(source).as_posix()
        if rel == "REPLACEMENT_LEDGER.md":
            continue  # this stage must write its own replacement ledger
        target = out / rel
        if target.is_symlink() or not target.is_file():
            errors.append(f"{rel}: source package file is missing from conformed output")
            continue
        prose = (original.suffix.lower() in text_exts and not is_non_manuscript_rel(rel)
                 and not is_bookkeeping_name(original.name)
                 and not original.name.lower().startswith("readme"))
        if not prose:
            if sha256_file(original) != sha256_file(target):
                errors.append(f"{rel}: conformance changed protected/non-prose source bytes")
            continue
        documents.append(rel)
        for path, counter in ((original, before), (target, after)):
            text = read_text_bounded(path)
            if text is None:
                errors.append(f"{rel}: cannot read document for content parity")
                continue
            counter.update(_template_norm_para(p) for p in re.split(r"\n\s*\n", text)
                           if p.strip())
    if not documents:
        errors.append("no editable manuscript text was available for guideline conformance")
    expected = before.copy()
    for row in exceptions:
        if row["kind"] in ("rewrap", "drop"):
            if not expected[row["source"]]:
                errors.append("replacement ledger source does not name an available paragraph")
            else:
                expected[row["source"]] -= 1
        if row["kind"] in ("rewrap", "addition"):
            expected[row["output"]] += 1
    expected += Counter()  # remove exhausted zero-count source paragraphs
    if expected != after:
        errors.append("conformed text differs from source without exact replacement-ledger accounting")
    allowed_extras = {"REPLACEMENT_LEDGER.md", "VISUAL_CHECK.md"}
    for target in template_package_files(out):
        rel = target.relative_to(out).as_posix()
        if rel not in names and rel not in allowed_extras:
            errors.append(f"{rel}: conformance added an undeclared package file")
    checked = sum(before.values())
    covered = sum((before & after).values())
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "documents": documents, "template_prose_left": [],
            "coverage": {"checked": checked, "covered": covered,
                         "ratio": covered / checked if checked else 0},
            "mode": "source-format-guidelines"}


def conform_context(ctx, source: Path) -> dict:
    """Bind a conformer's acceptance to its source and destination rules."""
    files = {p.relative_to(source).as_posix(): sha256_file(p)
             for p in template_package_files(source)}
    templates = {}
    if venue_templates_enabled():
        official = official_template_files(venue_id_of(ctx), ctx.root,
                                          manuscript_names=article_type_manuscript_names(ctx))
        for role in ("word", "latex"):
            for key, value in (official.get(role) or {}).items():
                for path in (value if isinstance(value, list) else [value]):
                    if isinstance(path, Path) and path.is_file():
                        templates[f"{role}/{key}/{path.name}"] = sha256_file(path)
    return {"source": files, "venue": venue_profile_of(ctx).to_dict(),
            "journal": journal_of(ctx), "policy": format_policy_of(ctx),
            "templates": templates}


def require_conform_context(ctx, sb: Path, source: Path) -> None:
    try:
        accepted = _write_read_json(sb / "CONFORM_CONTEXT.json")
        if accepted == conform_context(ctx, source):
            return
    except (OSError, ValueError, TypeError):
        pass
    die("conform stage is stale: its source or destination rules differ (or the legacy "
        "stage has no provenance). Rebuild with `conform --force --source "
        + str(source) + "` before continuing; existing output has been preserved.")


def journal_finalization_round(ctx) -> int:
    """A valid registered early stop is a completed journal workflow too."""
    configured = max(1, ctx.rounds_count())
    stop = ctx.state.get("stopped_early") or {}
    after = int(stop.get("after_round") or 0)
    if (int(stop.get("planned_rounds") or 0) == configured and 0 < after < configured
            and all((ctx.round_get(r) or {}).get("status") == "done"
                    for r in range(1, after + 1))
            and not any((ctx.round_get(r) or {}).get("status") == "done"
                        for r in range(after + 1, configured + 1))):
        return after
    return configured

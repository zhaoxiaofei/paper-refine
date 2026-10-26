# -*- coding: utf-8 -*-
# Part 15/17 of the pipeline -- executed by the
# loader, in order, in the loader's own module globals. Imports and names
# defined by earlier parts are therefore in scope exactly as they were in
# the single-file source.
from __future__ import annotations

# =====================================================================
# PERSISTENT PDF RENDERS (LaTeX compile + DOCX conversion)
#
# At each round close the version packages are COMPILED/CONVERTED, not just
# diffed: every LaTeX root (`\documentclass`) is built with
# `latexmk -pdf -interaction=nonstopmode -halt-on-error` inside a disposable
# copy, and every `.docx` is converted through the documented renderer chain
# (the docx-converter MCP tool first, then docx2pdf.sh, then LibreOffice). The
# PDFs are stored under <root>/pdfs/ (prune never touches them), so they outlive
# the whole `paper_pipeline.py` run. A compile/conversion failure is a WARNING:
# it is recorded in the manifest and printed, and it never fails a stage, a
# round or a decision. The pass starts no agent session.
# =====================================================================

PDF_DIRNAME = "pdfs"
PDF_MANIFEST = "manifest.json"
LATEX_COMPILE_TIMEOUT = 900
PDF_CONVERT_TIMEOUT = 900


def latex_root_documents(dirp: Path) -> list:
    """Relative paths of the `.tex`/`.ltx` files that are a COMPILE ROOT.

    A root carries `\\documentclass`; a fragment that is only `\\input`-ed by
    the root is not compiled on its own (it would fail without the preamble),
    and neither is an auxiliary or a `work/` scratch file.
    """
    out = []
    if not dirp.is_dir():
        return out
    for p in sorted(dirp.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".tex", ".ltx"):
            continue
        rel = p.relative_to(dirp)
        if p.name.startswith("~$") or _is_aux_doc(p.name) \
                or any(part == "work" for part in rel.parts[:-1]) \
                or is_evidence_rel(rel.as_posix()):
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"\\documentclass\b", head):
            out.append(rel.as_posix())
    return out


def compile_latex_pdf(pkg: Path, rel: str, out_pdf: Path,
                      timeout: int = LATEX_COMPILE_TIMEOUT,
                      keep_aux: bool = False, link_evidence: bool = False) -> dict:
    r"""Compile ONE LaTeX root into `out_pdf`; never raises.

    The build runs inside a DISPOSABLE COPY of the package: `latexmk` writes
    `.aux/.log/.pdf/...` next to its sources, and those by-products must not
    appear inside a version corpus (a `.pdf` is not an auxiliary suffix, so it
    would change the corpus digest -- an end result). `keep_aux` keeps the
    difference-tracking copies in that copy: a tracking `.tex` that was rewired
    to `\input` its tracked siblings (see compile_tracking_pdfs) cannot build
    without them. `link_evidence` SYMLINKS the read-only evidence areas
    (`raw_data/`, `human_review_feedback/`) into that copy instead
    of dropping them: a manuscript that `\includepdf{raw_data/...}` or
    `\input`s a data fragment needs them on disk, and the areas can be huge --
    the stage sandboxes link them for the same reason. They are read-only
    inputs, never written through.
    """
    exe = shutil.which("latexmk")
    if not exe:
        return {"ok": False, "tool": None,
                "error": "latexmk is not on PATH; the LaTeX sources were not compiled"}
    src = pkg / rel
    work = Path(tempfile.mkdtemp(prefix="paper_pdf_"))
    try:
        shutil.copytree(pkg, work, dirs_exist_ok=True,
                        # Name-based, not glob-based: the tracking token space is
                        # open (a1/w2/winner1/...), so _is_aux_doc() decides.
                        ignore=lambda _d, names: [
                            n for n in names
                            if n == "work" or n.startswith("~$")
                            or n in EVIDENCE_DIRNAMES
                            or (_is_aux_doc(n) and not keep_aux)])
        if link_evidence:
            for name in sorted(EVIDENCE_DIRNAMES):
                src_dir = pkg / name
                dst_dir = work / name
                if not src_dir.exists() or dst_dir.exists():
                    continue
                try:
                    os.symlink(str(src_dir.resolve()), str(dst_dir),
                               target_is_directory=True)
                except OSError:
                    # A platform without symlinks: a real copy is the fallback
                    # (correct, only slower), never a silently missing file.
                    shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True,
                                    symlinks=False)
        argv = [exe, "-pdf", "-interaction=nonstopmode", "-halt-on-error", Path(rel).name]
        # latexmk spawns pdflatex/bibtex children. Starting it in its own
        # process group and killing the GROUP on timeout stops those children
        # from writing into the build tree while `finally` removes it (a bare
        # `subprocess.run(timeout=...)` kills only latexmk itself).
        proc = subprocess.Popen(argv, cwd=str((work / rel).parent),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            import signal as _signal
            try:
                os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
            except (AttributeError, OSError):
                proc.kill()
            try:
                proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                pass
            raise
        out = (stdout or b"").decode("utf-8", "replace") \
            + (stderr or b"").decode("utf-8", "replace")
        pdf = (work / rel).with_suffix(".pdf")
        ok = bool(proc.returncode == 0 and pdf.is_file() and pdf.stat().st_size > 0)
        if ok:
            out_pdf.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf, out_pdf)
        errors = [ln.strip() for ln in out.splitlines() if ln.startswith("!")][:5]
        return {"ok": ok, "tool": "latexmk", "pages": _pdf_page_count(out_pdf) if ok else 0,
                "error": (None if ok else
                          (errors[0] if errors
                           else f"latexmk exited {proc.returncode} without a PDF")[:300]),
                "errors": errors}
    except (OSError, subprocess.SubprocessError, shutil.Error) as e:    # noqa: BLE001
        return {"ok": False, "tool": "latexmk", "error": f"{type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def convert_docx_to_pdf_persistent(docx: Path, out_dir: Path,
                                   timeout: int = PDF_CONVERT_TIMEOUT) -> dict:
    """Convert one DOCX to `<out_dir>/<stem>.pdf`; never raises."""
    try:
        res = render_docx_visual(docx, out_dir, None, timeout=timeout, page_images=False)
        return {"ok": bool(res.get("ok")), "tool": res.get("renderer"),
                "pages": res.get("pages") or 0, "error": res.get("error"),
                "fallbacks": res.get("fallbacks")}
    except Exception as e:                                              # noqa: BLE001
        return {"ok": False, "tool": None, "error": f"{type(e).__name__}: {e}"}


def _pdf_previous_records(stored: dict) -> dict:
    """{(label, rel): record} of a stored PDF manifest (for idempotent reuse)."""
    out = {}
    for s in (stored or {}).get("sets") or []:
        for d in s.get("documents") or []:
            out[(str(s.get("label") or ""), str(d.get("rel") or ""))] = d
    return out


def _docx_pdf_target(out_dir: Path, stem: str, latex_targets: set,
                     docx_defaults=(), chosen=()) -> Path:
    """The DOCX render path, moved aside when a LaTeX root owns `<stem>.pdf`.

    A package may legitimately carry `main.tex` and `main.docx`; both used to
    write `pdfs/<label>/main.pdf`, and the DOCX conversion silently overwrote
    the LaTeX render while both manifest rows reported ok. The moved-aside name
    must itself be free: a document actually named `main-docx.docx` renders to
    `main-docx.pdf`, so that name is skipped too.
    """
    target = Path(out_dir) / (stem + ".pdf")
    if target.resolve() not in latex_targets and target.resolve() not in chosen:
        return target
    base = stem + "-docx"
    n = 1
    while True:
        candidate = Path(out_dir) / (base + (".pdf" if n == 1 else f"-{n}.pdf"))
        resolved = candidate.resolve()
        if resolved not in latex_targets and resolved not in docx_defaults \
                and resolved not in chosen:
            return candidate
        n += 1


def render_pdf_set(ctx: Ctx, label: str, sources: list, out_root: Path,
                   previous: dict = None) -> list:
    """Compile/convert every document of ONE (label, sources) set; never raises."""
    docs, previous = [], previous or {}
    pkg_sources = [s for s in sources if not s[1]]
    latex_targets = set()
    for src, _prefix, _excluded in pkg_sources:
        if not src.is_dir():
            continue
        for rel in latex_root_documents(src):
            latex_targets.add((Path(out_root) / Path(rel).with_suffix(".pdf")).resolve())
    # Every DOCX's default render path. A moved-aside name must avoid these:
    # `main-docx.docx` legitimately renders to `main-docx.pdf`, which is exactly
    # the name the colliding `main.docx` would otherwise be moved to.
    docx_defaults = set()
    for f in list_track_files(sources, exts=(".docx",)):
        if f["rel"].split("/", 1)[0] == CODE_DIR:
            continue
        docx_defaults.add(
            (Path(out_root) / Path(f["rel"]).with_suffix(".pdf")).resolve())
    chosen = set()
    for src, _prefix, excluded in pkg_sources:
        if not src.is_dir():
            continue
        # LaTeX roots first (they carry the pages), then the .docx documents.
        for rel in latex_root_documents(src):
            digest = sha256_file(src / rel)
            out_pdf = out_root / Path(rel).with_suffix(".pdf")
            rec = _reuse_pdf_record(previous, label, rel, digest, out_pdf, "latex")
            if rec is None:
                # The evidence areas are read-only INPUTS the manuscript may
                # legitimately include (`\includepdf{raw_data/...}`): they are
                # linked into the build workspace, exactly like a stage sandbox.
                res = compile_latex_pdf(src, rel, out_pdf, link_evidence=True)
                rec = {"rel": rel, "kind": "latex", "out": out_pdf.relative_to(ctx.root).as_posix(),
                       "sha256": digest, "ok": bool(res.get("ok")), "tool": res.get("tool"),
                       "pages": res.get("pages") or 0, "error": res.get("error")}
            docs.append(rec)
    for f in list_track_files(sources, exts=(".docx",)):
        if f["rel"].split("/", 1)[0] == CODE_DIR:
            continue
        docx = f["path"]
        rel = f["rel"]
        out_dir = out_root / Path(rel).parent
        out_pdf = _docx_pdf_target(out_dir, docx.stem, latex_targets,
                                   docx_defaults, chosen)
        chosen.add(out_pdf.resolve())
        rec = _reuse_pdf_record(previous, label, rel, f["digest"], out_pdf, "docx")
        if rec is None:
            if out_pdf.name == docx.stem + ".pdf":
                res = convert_docx_to_pdf_persistent(docx, out_dir)
            else:
                # The renderer always writes `<out_dir>/<stem>.pdf`, so give
                # the colliding DOCX its own directory and move the result
                # to the distinct name; the LaTeX render is never touched.
                # `out_dir` exists only when the LaTeX compile above
                # succeeded (or the caller pre-created it), so create it
                # before mkdtemp: a failed LaTeX render must still leave the
                # DOCX attempt recorded, never raise out of render_pdf_set.
                out_dir.mkdir(parents=True, exist_ok=True)
                _tmp = Path(tempfile.mkdtemp(prefix=".docx-pdf-", dir=str(out_dir)))
                try:
                    res = convert_docx_to_pdf_persistent(docx, _tmp)
                    _made = _tmp / (docx.stem + ".pdf")
                    if res.get("ok") and _made.is_file():
                        out_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(_made), str(out_pdf))
                finally:
                    shutil.rmtree(_tmp, ignore_errors=True)
            rec = {"rel": rel, "kind": "docx",
                   "out": out_pdf.relative_to(ctx.root).as_posix(),
                   "sha256": f["digest"], "ok": bool(res.get("ok")),
                   "tool": res.get("tool"), "pages": res.get("pages") or 0,
                   "error": res.get("error"), "fallbacks": res.get("fallbacks")}
        docs.append(rec)
    return docs


def _reuse_pdf_record(previous: dict, label: str, rel: str, digest: str,
                      out_pdf: Path, kind: str) -> dict:
    """The stored record for an unchanged source, when its PDF is still there."""
    rec = previous.get((label, rel))
    if (rec and rec.get("ok") and rec.get("sha256") == digest and rec.get("kind") == kind
            and out_pdf.is_file() and out_pdf.stat().st_size > 0):
        fresh = dict(rec)
        fresh["cached"] = True
        return fresh
    return None


def run_pdf_conversion(ctx: Ctx, rounds=None, versions=None, include_original: bool = True,
                       quiet: bool = False) -> dict:
    """Compile/convert every requested version (and the original) into <root>/pdfs/."""
    rounds = [int(r) for r in (rounds or range(1, ctx.rounds_count() + 1))]
    versions = list(versions) if versions else None
    out_root = ctx.root / PDF_DIRNAME
    out_root.mkdir(parents=True, exist_ok=True)
    stored = read_json(out_root / PDF_MANIFEST) or {}
    previous = _pdf_previous_records(stored)
    # Like the tracking manifest, this one ACCUMULATES: a `track --round 2`
    # refreshes round 2's rows and keeps every other recorded set (and its
    # up-to-date check, so an unchanged source is never re-rendered).
    prev_sets = {str(s.get("label")): s for s in stored.get("sets") or []}
    set_order = [str(s.get("label")) for s in stored.get("sets") or []]

    def put_set(entry: dict) -> None:
        label = str(entry.get("label"))
        if label not in prev_sets:
            set_order.append(label)
        prev_sets[label] = entry

    manifest = {"generated": utcnow(), "pipeline_root": str(ctx.root), "sets": [], "notes": [
        "PDFs are written by `latexmk -pdf -interaction=nonstopmode -halt-on-error` for LaTeX "
        "roots (\\documentclass) and by the documented DOCX renderer chain (the docx-converter "
        "MCP tool first) for .docx documents.",
        "A compilation/conversion failure is a WARNING: it is recorded here and printed, and it "
        "never fails a stage, a round or a decision. prune never deletes this tree.",
    ]}
    if include_original:
        label = "original"
        docs = render_pdf_set(ctx, label, [(ctx.pristine, "", ())], out_root / label, previous)
        put_set({"label": label, "round": None, "version": None,
                 "note": f"the pre-conformed original ({ctx.pristine.name}/)",
                 "documents": docs})
        if not quiet and docs:
            _print_pdf_set(label, docs)
    for r in rounds:
        for vid in (versions if versions is not None else round_produced_ids(ctx, r)):
            if not is_fresh_vid(vid):
                continue
            srcs = fresh_package_sources(ctx, r, vid)
            if not any(s.is_dir() for s, _p, _e in srcs):
                continue
            label = f"r{r}_{vid}"
            docs = render_pdf_set(ctx, label, srcs, out_root / label, previous)
            put_set({"label": label, "round": r, "version": vid, "documents": docs})
            if not quiet and docs:
                _print_pdf_set(label, docs)
    manifest["sets"] = [prev_sets[k] for k in set_order]
    write_json_atomic(out_root / PDF_MANIFEST, manifest)
    write_text_atomic(out_root / "README.md", pdf_readme(manifest))
    return manifest


def _print_pdf_set(label: str, docs: list) -> None:
    for d in docs:
        if d.get("ok"):
            print(f"  [pdf] {label}: {d['rel']} -> {d['out']} ({d.get('tool')}"
                  + (f", {d['pages']} page(s)" if d.get("pages") else "") + ")")
        else:
            print(f"  [pdf] WARNING: {label}: {d['rel']} could not be rendered: "
                  f"{_md_cell(d.get('error'), 200)}")


def pdf_readme(manifest: dict) -> str:
    L = ["# Persistent PDF renders", "",
         f"Generated: {manifest['generated']}", "",
         "Every version's LaTeX roots are compiled with",
         "`latexmk -pdf -interaction=nonstopmode -halt-on-error` in a disposable copy of the",
         "package (so no build by-product ever lands in the corpus) and every `.docx` is",
         "converted through the documented renderer chain -- the `docx-converter` MCP tool",
         "first, then `docx2pdf.sh`, then LibreOffice. A failure is a WARNING, never a failed",
         "stage: the row says so and the run continues.", "",
         "`prune` never deletes this tree, so the renders outlive the pipeline run.", "",
         "| set | document | kind | tool | pages | result |", "|---|---|---|---|---|---|"]
    for s in manifest["sets"]:
        for d in s["documents"]:
            L.append(f"| {s['label']} | `{_md_cell(d['rel'], 80)}` | {d['kind']} | "
                     f"{_md_cell(d.get('tool') or '-')} | {d.get('pages') or '-'} | "
                     f"{'ok' if d.get('ok') else 'WARNING: ' + _md_cell(d.get('error'), 140)} |")
    L += ["", "## Notes", ""] + [f"- {n}" for n in manifest.get("notes") or []]
    L.append("")
    return "\n".join(L)


def pdf_summary(manifest: dict, rounds=None) -> None:
    """One-line summary of a PDF manifest (failures are warnings, never errors)."""
    rounds = set(int(r) for r in rounds) if rounds else None
    sets = [s for s in manifest["sets"]
            if rounds is None or int(s.get("round") or 0) in rounds]
    docs = [d for s in sets for d in s["documents"]]
    ok_n = sum(1 for d in docs if d.get("ok"))
    bad_n = len(docs) - ok_n
    root = Path(str(manifest.get("pipeline_root") or "."))
    print(f"[pdf] {ok_n} PDF(s) written"
          + (f", {bad_n} WARNING(S) (see {PDF_DIRNAME}/{PDF_MANIFEST})" if bad_n else "")
          + f" -> {PDF_DIRNAME}/")
    print(f"[pdf] manifest: {root / PDF_DIRNAME / PDF_MANIFEST}")
    print(f"[pdf] summary:  {root / PDF_DIRNAME / 'README.md'}")

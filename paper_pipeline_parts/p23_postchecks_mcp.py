# -*- coding: utf-8 -*-
# Part 23/25 of the pipeline -- the MCP stdio client and the visual
# render chain, split out of p06_postchecks (which had grown to 10,172 lines
# after the F083/F084 seed/render gates, over the project's 10,000-line cap).
# Executed by the loader, in order, in the loader's own module globals; the
# functions here are called at run time, after every part has loaded.
from __future__ import annotations

def mcp_stdio_tool_call(spec: dict, tool: str, arguments: dict,
                        timeout: float = 300) -> dict:
    """Drive one configured MCP stdio server for ONE tool call, then stop it.

    Minimal newline-delimited JSON-RPC: `initialize` ->
    `notifications/initialized` -> `tools/call`. The orchestrator seeds the
    venue-template renders itself, so it drives the operator's docx-converter
    MCP tool directly (Microsoft Word through PowerShell interop) instead of
    silently falling back to a lower-fidelity shim. This is the ORCHESTRATOR's
    own render chain; the agent prompts put `docx2pdf.sh` first.
    """
    argv = [str(spec.get("command") or ""), *[str(a) for a in spec.get("args") or []]]
    if not argv[0]:
        return {"ok": False, "error": "the MCP server entry names no command"}
    launch_env = None
    if spec.get("env"):
        launch_env = dict(os.environ, **{str(k): str(v) for k, v in spec["env"].items()})
    launch_cwd = spec.get("cwd") or None
    try:
        # Its OWN process group: a timeout must kill the whole chain
        # (bash -> PowerShell -> Word), not only the node wrapper (F29).
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1,
                                encoding="utf-8", errors="replace",
                                env=launch_env, cwd=launch_cwd,
                                **_render_popen_kwargs())
    except OSError as e:
        return {"ok": False, "error": f"the MCP server would not start: {e}"}
    # A misbehaving MCP server must not grow memory without bound: queue only a
    # bounded number of lines/bytes and record a flood instead of blocking the
    # producer or allocating until OOM (the 2026-10-28 audit's F80).
    MAX_MCP_LINES = 4096
    MAX_MCP_LINE_BYTES = 1 << 20
    MAX_MCP_QUEUED_BYTES = 8 << 20      # TOTAL bytes waiting in the queue
    MAX_MCP_STDERR_KEEP = 4096          # per-line tail kept for the error report
    lines = queue.Queue(maxsize=MAX_MCP_LINES)
    queued_bytes = [0]
    queue_lock = threading.Lock()
    flooded = threading.Event()
    stderr_flooded = threading.Event()
    err_tail = deque(maxlen=6)

    def pump(stream) -> None:
        try:
            while True:
                line = stream.readline(MAX_MCP_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_MCP_LINE_BYTES:
                    flooded.set()
                    continue
                with queue_lock:
                    if queued_bytes[0] + len(line) > MAX_MCP_QUEUED_BYTES:
                        flooded.set()
                        continue
                    try:
                        lines.put_nowait(line)
                    except queue.Full:
                        flooded.set()
                    else:
                        queued_bytes[0] += len(line)
        finally:
            try:
                lines.put_nowait(None)
            except queue.Full:
                pass

    def pump_err(stream) -> None:
        try:
            while True:
                line = stream.readline(MAX_MCP_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_MCP_LINE_BYTES:
                    stderr_flooded.set()
                    continue
                err_tail.append(line[-MAX_MCP_STDERR_KEEP:])
        except (OSError, ValueError):
            pass

    threading.Thread(target=pump, args=(proc.stdout,), daemon=True).start()
    threading.Thread(target=pump_err, args=(proc.stderr,), daemon=True).start()

    def stop_tree() -> None:
        """Kill the server AND its grandchildren (F29)."""
        if os.name == "nt":
            if proc.poll() is None:
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True, timeout=30)
                with contextlib.suppress(OSError):
                    proc.kill()
        else:
            # Give the server a chance to run its OWN tree kill first (F042):
            # runFile's wrapper is in its own session, so killpg alone reached
            # only the node server and left bash -> PowerShell -> Word alive.
            # SIGTERM triggers the server's handler, which kills every active
            # child tree (including the recorded Windows pids) before exiting.
            with contextlib.suppress(OSError, ProcessLookupError, PermissionError):
                proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=2)
            # killpg by the WRAPPER's pid works even after the wrapper exited:
            # start_new_session made that pid the group id. It is the backstop
            # for a server that ignored SIGTERM.
            with contextlib.suppress(OSError, ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            with contextlib.suppress(OSError):
                proc.kill()

    def failure(prefix: str) -> dict:
        """`prefix` plus what the SERVER itself said, when saying nothing.

        The handshake used to discard the server's stderr, so a server that
        died on startup (a missing npm dependency -- the 2026-10-14 state of
        the docx-compare/docx-converter copies) surfaced as the bare "did not
        answer initialize()". One bounded wait drains the pipe, and the tail
        travels into the manifest, so the operator sees the real error.
        """
        # Stop the tree BEFORE the 2-second drain: waiting first let a
        # grandchild (bash -> PowerShell -> Word) keep running and writing for
        # the whole diagnostic window (F29).
        stop_tree()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=2)
        time.sleep(0.05)
        text = "".join(err_tail).strip().replace("\n", " | ")
        bits = [prefix]
        if proc.returncode is not None:
            bits.append(f"the server exited with code {proc.returncode}")
        if text:
            bits.append(f"stderr: {text[-300:]}")
        if flooded.is_set():
            bits.append("the server flooded its stdout; excess output was dropped")
        if stderr_flooded.is_set():
            bits.append("the server flooded its stderr; excess output was dropped")
        return {"ok": False, "error": "; ".join(bits)}

    def send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def wait_for(rid: int, deadline: float):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                line = lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if line is None:
                return None
            with queue_lock:
                if queued_bytes[0]:
                    queued_bytes[0] = max(0, queued_bytes[0] - len(line))
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except (ValueError, RecursionError):
                # A deeply nested line raises RecursionError, not ValueError:
                # letting it escape crashed the orchestrator mid-render instead
                # of degrading to the next backend with a recorded error (F072).
                continue
            # JSON-RPC ids are per DIRECTION: a legal server->client REQUEST
            # (e.g. `ping`) may carry the same id as our tools/call. Only a
            # RESPONSE -- no `method`, and a result or error -- answers us
            # (F044).
            if (isinstance(msg, dict) and "method" not in msg
                    and ("result" in msg or "error" in msg)
                    and msg.get("id") == rid):
                return msg

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "paper_pipeline", "version": VERSION}}})
        init = wait_for(1, time.monotonic() + min(float(timeout), 60.0))
        if init is None:
            return failure("the MCP server did not answer initialize()")
        if init.get("error"):
            return {"ok": False, "error": f"initialize() failed: {init['error']}"}
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": tool, "arguments": arguments}})
        rep = wait_for(2, time.monotonic() + float(timeout))
        if rep is None:
            return failure(f"the MCP tool {tool} did not answer within {int(timeout)}s")
        if rep.get("error"):
            return {"ok": False, "error": f"the MCP tool {tool} failed: {rep['error']}"}
        out = {"ok": True, "result": rep.get("result") or {}}
        flood_warnings = []
        if flooded.is_set():
            flood_warnings.append("the server flooded its stdout; excess output was dropped")
        if stderr_flooded.is_set():
            flood_warnings.append("the server flooded its stderr; excess output was dropped")
        if flood_warnings:
            out["warnings"] = flood_warnings
        return out
    except (OSError, ValueError, RecursionError) as e:                  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        with contextlib.suppress(OSError):
            proc.stdin.close()
        stop_tree()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def mcp_convert_docx_to_pdf(spec: dict, docx: Path, timeout: float = 300) -> dict:
    """Convert one DOCX through the operator's docx-converter MCP tool.

    The tool writes `<stem>.pdf` NEXT TO the file it is handed, so callers pass
    a disposable copy and read-only inputs never change.
    """
    rep = mcp_stdio_tool_call(spec, DOCX_MCP_TOOL, {"docxPath": str(docx)}, timeout=timeout)
    if not rep.get("ok"):
        return rep
    result = rep.get("result") or {}
    if result.get("isError"):
        text = " ".join(str(c.get("text") or "") for c in result.get("content") or []
                        if isinstance(c, dict))
        return {"ok": False, "error": f"the MCP tool reported an error: {text[:200]}"}
    pdf = Path(docx).with_suffix(".pdf")
    if not pdf.is_file() or pdf.stat().st_size == 0:
        return {"ok": False,
                "error": f"the MCP tool returned success but wrote no PDF next to {Path(docx).name}"}
    return {"ok": True, "pdf": pdf}


def docx_compare_mcp_spec() -> dict:
    """The configured `docx-compare` MCP server entry, {} when it is unusable.

    Being configured is not enough: the entry has to name a command that is
    still on this machine (the same probe `mcp_server_configured` applies). An
    empty dict sends the redline chain to its next backend and is reported in
    the manifest, so a missing server is never mistaken for a failed compare.
    """
    if not mcp_server_configured(DOCX_COMPARE_MCP_SERVER):
        return {}
    spec = mcp_server_spec(DOCX_COMPARE_MCP_SERVER)
    cmd = str(spec.get("command") or "")
    if not cmd:
        return {}
    # `~` IS expanded here, like the sibling probe in `mcp_server_configured`:
    # a home-relative command used to read as "not installed" and silently
    # vanish from the redline chain.
    present = (Path(os.path.expanduser(cmd)).exists() if cmd.startswith(("/", "~"))
               else bool(shutil.which(cmd)))
    return spec if present else {}


def mcp_compare_docx(spec: dict, base: Path, revised: Path, out: Path,
                     timeout: float = 900) -> dict:
    """Write a Word-native tracked-changes redline through the compare MCP tool.

    The tool drives `docxcompare.sh` -> PowerShell -> `Word.Application
    .CompareDocuments`; it is handed the real base/revised paths and an explicit
    output path (`<pipeline-managed auxiliary>.docx`), never an input path as its
    output. Success is "the tool answered AND `out` is a readable OOXML package"
    -- the same bar every other redline backend is held to.
    """
    rep = mcp_stdio_tool_call(spec, DOCX_COMPARE_MCP_TOOL,
                              {"originalPath": str(base), "revisedPath": str(revised),
                               "outputPath": str(out)}, timeout=timeout)
    if not rep.get("ok"):
        return {"ok": False, "error": rep.get("error")}
    result = rep.get("result") or {}
    if result.get("isError"):
        text = " ".join(str(c.get("text") or "") for c in result.get("content") or []
                        if isinstance(c, dict))
        return {"ok": False, "error": f"the MCP tool reported an error: {text[:300]}"}
    if not out.is_file() or out.stat().st_size == 0:
        return {"ok": False,
                "error": f"the MCP tool returned success but wrote no output at {out}"}
    return {"ok": True}


def visual_renderer_choices() -> list:
    """Every usable DOCX->PDF renderer, in the ORCHESTRATOR's own order.

    The operator's docx-converter MCP tool comes FIRST (Microsoft Word through
    PowerShell interop, the highest-fidelity renderer); `docx2pdf.sh` -- the
    script that MCP tool drives internally, and the converter the agent prompts
    tell an agent to run first -- is the fallback when the server is not
    installed or cannot start, and LibreOffice is the last resort.

    This is the orchestrator's render chain (venue-template renders, PDF
    staging), not the agents' route order: the prompts put `docx2pdf.sh` first.
    """
    out = []
    if mcp_server_configured(DOCX_MCP_SERVER):
        spec = mcp_server_spec(DOCX_MCP_SERVER)
        cmd = str(spec.get("command") or "")
        present = (Path(os.path.expanduser(cmd)).exists() if cmd.startswith(("/", "~"))
                   else bool(shutil.which(cmd)))
        if cmd and present:
            out.append((f"mcp:{DOCX_MCP_SERVER}", spec))
    here = Path(__file__).resolve().parent
    for cand in (here / "docx2pdf.sh", shutil.which("docx2pdf.sh")):
        if cand and Path(cand).is_file() and os.access(str(cand), os.X_OK):
            out.append(("word", Path(cand)))
            break
    for exe in ("soffice", "libreoffice"):
        p = shutil.which(exe)
        if p:
            out.append(("libreoffice", Path(p)))
            break
    return out


def visual_renderer_choice() -> tuple:
    """(name, payload) for the BEST renderer: MCP first, then Word, then LibreOffice."""
    choices = visual_renderer_choices()
    return choices[0] if choices else ("none", None)


def _pdf_page_count(pdf: Path) -> int:
    exe = shutil.which("pdfinfo")
    if exe:
        try:
            out = subprocess.run([exe, str(pdf)], capture_output=True, timeout=60).stdout
            m = re.search(rb"^Pages:\s*(\d+)", out or b"", re.M)
            if m:
                return int(m.group(1))
        except (OSError, subprocess.SubprocessError):
            pass
    return 0


def _child_output(raw) -> str:
    """A child process's stdout/stderr as text, never fatal on a non-UTF-8 locale.

    The renderers this pipeline drives are Windows-interop shims; their
    diagnostics arrive in the console's own code page, and decoding those as
    strict UTF-8 must not turn a rendered PDF into a failed session.
    """
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return raw or ""


def _page_png_names(out_dir: Path, stem: str) -> list:
    """The page PNGs pdftoppm wrote for `stem`, in PAGE order.

    `stem` is matched literally (a stem like `Papers[1]` is not a glob
    character class), and the trailing page number sorts numerically so
    page-10 follows page-2.
    """
    def key(name: str):
        m = re.search(r"-(\d+)\.png$", name)
        return (int(m.group(1)) if m else 10 ** 9, name)
    # EXACT `stem-<page>.png`: the old prefix test also kept another document's
    # pages when `main.tex` and `main.docx` shared an output directory
    # (`main-docx-1.png`), mixing two documents into one visual pass.
    pat = re.compile(r"^" + re.escape(stem) + r"-\d+\.png$", re.I)
    return sorted((p.name for p in Path(out_dir).iterdir()
                   if p.is_file() and pat.match(p.name)), key=key)


def _render_popen_kwargs() -> dict:
    """Run the renderer in its own process group (timeout must kill the tree)."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _kill_render_tree(proc) -> None:
    """Kill a timed-out Word/LibreOffice renderer AND its grandchildren."""
    if os.name == "nt":
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
    else:
        with contextlib.suppress(OSError, ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def _kill_recorded_windows_pids(pid_file) -> None:
    """Kill the Windows pids a Word converter recorded for THIS render.

    WSL's ``os.killpg`` reaches the Linux side only: the Word/COM server the
    PowerShell started is a WINDOWS process and survives it, so a timed-out
    conversion leaves ``WINWORD.EXE`` running and poisons every later render
    (the 2026-11-24 baseline stall left a dozen orphans, and each killed run
    added more).  ``docx2pdf.sh`` writes the pids it started to
    ``DOCX_MCP_WINDOWS_PID_FILE`` before and just after it creates its Word
    instance, so kill exactly those and never a Word instance we did not start.
    """
    try:
        text = Path(str(pid_file)).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    exe = shutil.which("taskkill.exe") or shutil.which("taskkill")
    if not exe:
        return
    for raw in text.split():
        pid = raw.strip()
        if not pid.isdigit():
            continue
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run([exe, "/F", "/T", "/PID", pid],
                           capture_output=True, timeout=30)


def _run_render_subprocess(argv, timeout, cwd=None, env=None):
    """`subprocess.run` with a timeout that kills the renderer's whole tree.

    stdout/stderr go to TEMPORARY FILES and are read back only up to
    MAX_TOOL_OUTPUT_BYTES: the renderer is driven by an untrusted package, so a
    flood must fail the render instead of allocating without bound (F25).
    """
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        proc = subprocess.Popen(
            [str(a) for a in argv], stdout=out_f, stderr=err_f, stdin=subprocess.DEVNULL,
            cwd=cwd, env=env, **_render_popen_kwargs())
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_render_tree(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=30)              # reap; never leave a zombie
            raise
        out_f.seek(0, os.SEEK_END)
        err_f.seek(0, os.SEEK_END)
        out_size, err_size = out_f.tell(), err_f.tell()
        if out_size > MAX_TOOL_OUTPUT_BYTES or err_size > MAX_TOOL_OUTPUT_BYTES:
            raise ToolOutputOverBudget(
                f"renderer output over {MAX_TOOL_OUTPUT_BYTES} bytes "
                f"(stdout={out_size}, stderr={err_size})")
        out_f.seek(0)
        err_f.seek(0)
        out = out_f.read(MAX_TOOL_OUTPUT_BYTES + 1).decode("utf-8", "replace")
        err = err_f.read(MAX_TOOL_OUTPUT_BYTES + 1).decode("utf-8", "replace")
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def _render_output_body_problem(path: Path) -> str:
    """'' when a renderer's PDF carries content between header and trailer.

    A signature-only stub (`%PDF-1.4\n%%EOF\n`) has both markers and no body;
    it is not a render even though it is, structurally, a "complete signature".
    """
    try:
        size = path.stat().st_size
        # A bounded HEAD supplies the body, a bounded TAIL the trailer: a valid
        # PDF over 4 MiB keeps its %%EOF at the end (F098).
        limit = min(size, 4 * 1024 * 1024)
        tail_limit = min(size, 64 * 1024)
        with path.open("rb") as fh:
            data = fh.read(limit)
            if size > limit:
                fh.seek(max(0, size - tail_limit)); tail = fh.read(tail_limit)
            else:
                tail = data
    except OSError as e:
        return f"{type(e).__name__}: {e}"
    _nl = data.find(b"\n")
    _after = data[_nl + 1:] if _nl >= 0 else b""
    # For a small file `tail` IS `data`, so measure the trailer in `_after`.
    _src = _after if size <= limit else tail
    _eof = _src.rfind(b"%%EOF")
    if _eof < 0:
        return "no %%EOF trailer in the PDF body"
    _before = _after[:_eof] if size <= limit else _after
    if size > limit and not _before.strip():
        _before = tail[:_eof]
    if not _before.strip():
        return "no PDF body between the %PDF- header and the %%EOF trailer"
    return ""


def pdf_signature_problem(path: Path) -> str:
    """'' when `path` looks like a complete PDF, else the reason it does not.

    A non-empty output file is not a render. `docx2pdf.sh` has always checked
    the `%PDF-` header and the `%%EOF` trailer; the in-process renderer and the
    persistent-PDF cache did not, so a converter that wrote one garbage byte
    and exited 0 was recorded `ok`, and a later run reused the same bytes from
    the cache (PR151-164). The trailer must be near the END, not merely
    somewhere in the bytes: a truncated file whose text stream contains the
    marker must not pass (the 2026-10-28 audit's F64 made the same distinction
    for the shell converter).
    """
    try:
        size = path.stat().st_size
        if size <= 0:
            return "the file is empty"
        with path.open("rb") as fh:
            head = fh.read(1024)
            if not head.startswith(b"%PDF-"):
                # The header is the FILE MAGIC at offset zero. `in the first
                # 1024 bytes` accepted a text file with the marker somewhere
                # near the top as a "PDF" (F-074).
                return "no %PDF- header at the start of the file"
            tail_len = min(2048, size)
            fh.seek(-tail_len, os.SEEK_END)
            if b"%%EOF" not in fh.read(tail_len):
                return ("no %%EOF trailer in the last 2048 bytes "
                        "(the file is truncated or not a PDF)")
    except OSError as e:
        return f"{type(e).__name__}: {e}"
    return ""


def render_docx_visual(docx: Path, out_dir: Path, renderer=None,
                       timeout: float = 900, page_images: bool = True) -> dict:
    """Render ONE DOCX to PDF + page PNGs under `out_dir`.

    `renderer` pins ONE renderer (tests, retries); None tries the whole choice
    list in order -- the docx-converter MCP tool first, then docx2pdf.sh, then
    LibreOffice -- because pagination, fonts and headers/footers differ between
    Word and LibreOffice. The renderer that actually produced the PDF, and any
    lower-fidelity fallbacks, are recorded so the agents and the decision report
    can state them.

    `page_images=False` skips the page-PNG pass (the persistent PDF store of
    `run_pdf_conversion()` needs the PDF only; the agents' visual passes keep
    the default).
    """
    if renderer is None:
        choices = visual_renderer_choices()
        if not choices:
            return {"ok": False, "renderer": "none",
                    "error": "no DOCX->PDF renderer is installed (docx-converter MCP tool, "
                             "docx2pdf.sh or LibreOffice)"}
        failures = []
        for cand in choices:
            # The fallback loop must carry the caller's policy: dropping them
            # here silently restored the 900 s default and re-enabled the page
            # PNGs that `page_images=False` exists to skip.
            res = render_docx_visual(docx, out_dir, cand, timeout=timeout,
                                     page_images=page_images)
            if res.get("ok"):
                if failures:
                    res["fallbacks"] = failures
                return res
            failures.append({"renderer": cand[0], "error": res.get("error")})
        return {"ok": False, "renderer": choices[0][0], "attempts": failures,
                "error": "no renderer produced a PDF: "
                         + "; ".join(f"{f['renderer']}: {f['error']}" for f in failures)[:300]}
    name, exe = renderer
    out_dir.mkdir(parents=True, exist_ok=True)
    if name == "none" or exe is None:
        return {"ok": False, "renderer": "none", "error": "no DOCX->PDF renderer on PATH"}
    tmp = Path(tempfile.mkdtemp(prefix="vrender_", dir=str(out_dir)))
    try:
        src = tmp / docx.name
        shutil.copy2(docx, src)
        proc = None
        if name.startswith("mcp:"):
            conv = mcp_convert_docx_to_pdf(exe, src, timeout=timeout)
            if not conv.get("ok"):
                return {"ok": False, "renderer": name, "error": conv.get("error")}
            pdf = Path(conv["pdf"])
        elif name == "word":
            # The script bounds its own call, but only the CALLER can kill the
            # Windows Word/COM server it started (a WSL process-group kill does
            # not reach it).  Hand it a pid file and clean up after a timeout,
            # so a hung Word cannot poison the next render.
            pid_file = tmp / "windows-pids"
            word_env = dict(os.environ, DOCX_MCP_WINDOWS_PID_FILE=str(pid_file))
            try:
                proc = _run_render_subprocess([str(exe), str(src)], timeout=timeout,
                                              cwd=str(tmp), env=word_env)
            except subprocess.TimeoutExpired:
                _kill_recorded_windows_pids(pid_file)
                raise
            except ToolOutputOverBudget as exc:
                _kill_recorded_windows_pids(pid_file)
                return {"ok": False, "renderer": name, "error": str(exc)}
            if proc.returncode in (124, 137):
                # docx2pdf.sh's own bound fired (124) or its SIGKILL grace did.
                _kill_recorded_windows_pids(pid_file)
            pdf = src.with_suffix(".pdf")
        else:
            profile = tmp / "lo_profile"
            try:
                proc = _run_render_subprocess(
                    [str(exe), "--headless",
                     f"-env:UserInstallation=file://{profile}",
                     "--convert-to", "pdf", "--outdir", str(tmp), str(src)],
                    timeout=timeout)
            except ToolOutputOverBudget as exc:
                return {"ok": False, "renderer": name, "error": str(exc)}
            pdf = tmp / (src.stem + ".pdf")
        if not pdf.is_file() or pdf.stat().st_size == 0:
            detail = (_child_output(getattr(proc, "stderr", None))
                      + _child_output(getattr(proc, "stdout", None))) \
                .strip().replace("\n", " ")[:200]
            return {"ok": False, "renderer": name,
                    "error": f"the renderer produced no PDF: {detail}"}
        # A non-empty file is not a render. Validate the signature BEFORE
        # moving it into place (and before the page-image pass), so a broken
        # converter cannot be recorded `ok` and cached for the next run.
        _sig = pdf_signature_problem(pdf)
        if _sig:
            detail = (_child_output(getattr(proc, "stderr", None))
                      + _child_output(getattr(proc, "stdout", None))) \
                .strip().replace("\n", " ")[:200]
            return {"ok": False, "renderer": name,
                    "error": f"the renderer produced a non-PDF file ({_sig})"
                             + (f": {detail}" if detail else "")}
        # A 15-byte `%PDF-1.4\n%%EOF\n` passes the two SIGNATURE markers but
        # renders nothing: it was recorded as `ok: True, pages: 0`, so a
        # converter that wrote a header and a trailer satisfied the render gate
        # (F31). A real render always writes content between them. The check is
        # applied to the renderer's OUTPUT only; `pdf_signature_problem` keeps
        # its documented signature contract for evidence/cache readers.
        _body = _render_output_body_problem(pdf)
        if _body:
            detail = (_child_output(getattr(proc, "stderr", None))
                      + _child_output(getattr(proc, "stdout", None))) \
                .strip().replace("\n", " ")[:200]
            return {"ok": False, "renderer": name,
                    "error": f"the renderer produced a non-render ({_body})"
                             + (f": {detail}" if detail else "")}
        final_pdf = out_dir / (docx.stem + ".pdf")
        shutil.move(str(pdf), str(final_pdf))
        pages = _pdf_page_count(final_pdf)
        pngs = []
        warnings = []
        if page_images and shutil.which("pdftoppm"):
            prefix = out_dir / docx.stem
            try:
                subprocess.run(["pdftoppm", "-r", str(VISUAL_PAGE_DPI), "-png",
                                str(final_pdf), str(prefix)],
                               capture_output=True, timeout=600)
            except (OSError, subprocess.SubprocessError) as e:      # noqa: BLE001
                # The PDF has already been moved into place: a page-image
                # timeout must not turn a successful render into a failure and
                # send the chain to a lower-fidelity renderer.
                warnings.append(f"page images not produced ({type(e).__name__}: {e})")
            # Page numbers sort numerically (page-10 after page-2), and the
            # stem is matched literally: a stem like `Papers[1]` made the old
            # glob a character class and returned zero pages.
            pngs = _page_png_names(out_dir, docx.stem)
            pages = pages or len(pngs)
        result = {"ok": True, "renderer": name, "pdf": final_pdf.name,
                  "pages": pages or 0, "pngs": pngs}
        if warnings:
            result["warnings"] = warnings
        return result
    except (OSError, subprocess.SubprocessError) as e:                  # noqa: BLE001
        return {"ok": False, "renderer": name, "error": f"{type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)



#!/usr/bin/env python3
"""Render every stage prompt from one checkout and print a sha256 per stage.

The `--execution-profile high` contract is byte-identity with the pipeline as it
was before the profile feature existed.  This script is one half of that proof:

    python3 .paper_test/render_stage_prompts.py <checkout>   # hashes
    python3 .paper_test/render_stage_prompts.py <checkout> --dump DIR
    python3 .paper_test/render_stage_prompts.py <checkout> --medium  # sizes table

Run it against a baseline checkout (e.g. `git archive HEAD | tar -x -C
<dir>`) and against the working tree, then compare the two --dump directories.
The checkout's ABSOLUTE PATH is normalised out before hashing, because several
prompt blocks embed the pipeline's own path.

The four OPTIONAL-TOOL probes are pinned (see `pin_optional_tool_probes`), so a
hash pins the PROMPT text and not the machine's PATH, MCP config or home
directory: the same values reproduce with and without `zot`/`docx` installed.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import sys
import tempfile
from pathlib import Path


def pin_optional_tool_probes(P) -> None:
    """Fix the environment-dependent prompt probes to a bare machine.

    The stage prompts embed the result of four probes of the DEVELOPER's box:
    the optional `docx`/`zot` CLIs on PATH, the `zot` credential profile in the
    home directory, and the visual renderers found on PATH / in the Codex MCP
    config. A frozen hash must pin the PROMPT, not the box it was captured on,
    so every probe is pinned to the documented NO-OPTIONAL-TOOLING machine: no
    docx, no zot, no zot profile, no visual renderer.
    """
    P.docx_cli_available = lambda: False
    P.zot_cli_available = lambda: False
    P.zotero_remote_hint = lambda: P.ZOT_REMOTE_HINT_UNKNOWN
    P.probe_available = lambda spec: False
    # `visual_tools_summary()` caches its first answer in this module global.
    P._VISUAL_TOOLS_CACHE = None


def _load_pipeline(checkout: Path):
    """The checkout's pipeline module, with the optional-tool probes pinned."""
    sys.path.insert(0, str(checkout))
    for mod in list(sys.modules):
        if mod == "paper_pipeline":
            del sys.modules[mod]
    P = importlib.import_module("paper_pipeline")
    pin_optional_tool_probes(P)
    return P


def _prepare_sandbox(checkout: Path, sandbox):
    """A FIXED sandbox path with one stub base document.

    Every prompt embeds the sandbox path, so two renders of two checkouts must
    agree on it or the comparison measures the temp dir.
    """
    sb = Path(sandbox) if sandbox is not None else Path(
        os.environ.get("PAPER_RENDER_SANDBOX")
        or (checkout.parent / "pr-render-sandbox" / "r1_guided_review"))
    sb = sb.resolve()
    if sb.exists():
        import shutil
        shutil.rmtree(sb, ignore_errors=True)
    (sb / "base").mkdir(parents=True)
    (sb / "base" / "manuscript.md").write_text("# m\n\ntext.\n", encoding="utf-8")
    return sb


def _stage_calls(P, sb, prof, execution_profile: str) -> dict:
    """The eleven stage builders, bound to one sandbox and one profile."""
    return {
        # `execution_profile` is passed to EVERY builder: the `high` render (the
        # byte-identity proof) then equals the pre-profile pipeline, and the
        # `medium` render produces the sizes the README table reports.
        "review": lambda: P.review_prompt(sb, "r1_guided_review", 1, venue=prof, scope="full",
                                          execution_profile=execution_profile),
        "review_split_a": lambda: P.review_prompt(sb, "r1_guided_review", 1, venue=prof, split="a",
                                                  execution_profile=execution_profile),
        "review_scoped": lambda: P.review_prompt(sb, "r1_guided_review", 1, venue=prof,
                                                 scope="formatting-writing",
                                                 execution_profile=execution_profile),
        "cold_start_review": lambda: P.cold_start_review_prompt(
            sb, "r1_cold_start_review", 1, venue=prof, execution_profile=execution_profile),
        "audit": lambda: P.audit_prompt(sb, "r1_audit", 1, venue=prof,
                                        execution_profile=execution_profile),
        "revise": lambda: P.revise_prompt(sb, "r1_a2_revise", 1, venue=prof, audit=True,
                                          execution_profile=execution_profile),
        "integrate": lambda: P.integrate_prompt(sb, "r1_i1", 1, "v1", ["v2", "v3"], venue=prof,
                                                execution_profile=execution_profile),
        "rewrite": lambda: P.rewrite_prompt(sb, "r1_w1", 1, venue=prof,
                                            execution_profile=execution_profile),
        "judge": lambda: P.judge_prompt(sb, "judge_x_j1", 1, "v1", 1, 2, [], venue=prof,
                                        execution_profile=execution_profile),
        "revision_audit": lambda: P.revision_audit_prompt(sb, "r1_revision_audit", 1,
                                                          execution_profile=execution_profile),
        "revision_repair": lambda: P.revision_repair_prompt(sb, "r1_repair", 1, 3,
                                                            execution_profile=execution_profile),
    }


def _normalise(text: str, checkout: Path, sb: Path) -> str:
    # The SANDBOX path first (it may live UNDER the checkout, so normalising
    # the checkout first would fold it into <CHECKOUT> inconsistently), then
    # the checkout's own path, which several blocks embed.
    text = text.replace(str(sb.resolve()), "<SANDBOX>")
    return text.replace(str(checkout.resolve()), "<CHECKOUT>")


def render(checkout: Path, execution_profile: str = "high", sandbox=None) -> dict:
    P = _load_pipeline(checkout)
    prof = P.load_venue_profile("generic")
    sb = _prepare_sandbox(checkout, sandbox)
    return {name: _normalise(fn(), checkout, sb)
            for name, fn in _stage_calls(P, sb, prof, execution_profile).items()}


def render_with_rules(checkout: Path, execution_profile: str = "medium",
                      sandbox=None) -> dict:
    """`{stage: {"text": prompt, "rules": paged rules text}}` for one profile.

    One stage at a time, so each stage's `INSTRUCTIONS/PROFILE_RULES.md` is
    captured before the next stage overwrites it.  The equivalence check in
    `.paper_test/test_execution_profile.py` compares each entry with the `high`
    render of the same stage (AGENTS.md rule 12): the rule text `high` inlines
    must be carried by the prompt or by this file, and the file must invent
    nothing.
    """
    P = _load_pipeline(checkout)
    prof = P.load_venue_profile("generic")
    sb = _prepare_sandbox(checkout, sandbox)
    rules_path = sb / P.PROFILE_RULES_REL
    out = {}
    for name, fn in _stage_calls(P, sb, prof, execution_profile).items():
        rules_path.unlink(missing_ok=True)
        text = fn()
        rules = rules_path.read_text(encoding="utf-8") if rules_path.is_file() else ""
        out[name] = {"text": _normalise(text, checkout, sb),
                     "rules": _normalise(rules, checkout, sb)}
    return out


def main(argv: list) -> int:
    checkout = Path(argv[0]).resolve()
    dump = None
    if "--dump" in argv:
        dump = Path(argv[argv.index("--dump") + 1])
        dump.mkdir(parents=True, exist_ok=True)
    profile = "medium" if "--medium" in argv else "high"
    texts = render(checkout, profile)
    for name, text in texts.items():
        if dump:
            (dump / f"{name}.md").write_text(text, encoding="utf-8")
        print(f"{name:18} {len(text):>8}  {hashlib.sha256(text.encode()).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

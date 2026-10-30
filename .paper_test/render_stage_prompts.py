#!/usr/bin/env python3
"""Render every stage prompt from one checkout and print a sha256 per stage.

The `--execution-profile high` contract is byte-identity with the pipeline as it
was before the profile feature existed.  This script is one half of that proof:

    python3 .paper_test/render_stage_prompts.py <checkout>   # hashes
    python3 .paper_test/render_stage_prompts.py <checkout> --dump DIR

Run it against a baseline checkout (e.g. `git archive HEAD | tar -x -C
<dir>`) and against the working tree, then compare the two --dump directories.
The checkout's ABSOLUTE PATH is normalised out before hashing, because several
prompt blocks embed the pipeline's own path.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import sys
import tempfile
from pathlib import Path


def render(checkout: Path) -> dict:
    sys.path.insert(0, str(checkout))
    for mod in list(sys.modules):
        if mod == "paper_pipeline":
            del sys.modules[mod]
    P = importlib.import_module("paper_pipeline")
    prof = P.load_venue_profile("generic")
    # A FIXED sandbox path: every prompt embeds it, so two renders of two
    # checkouts must agree on it or the comparison measures the temp dir.
    sb = Path(os.environ.get("PAPER_RENDER_SANDBOX")
              or (checkout.parent / "pr-render-sandbox" / "r1_targeted_review"))
    sb = sb.resolve()
    if sb.exists():
        import shutil
        shutil.rmtree(sb, ignore_errors=True)
    (sb / "base").mkdir(parents=True)
    (sb / "base" / "manuscript.md").write_text("# m\n\ntext.\n", encoding="utf-8")
    calls = {
        "review": lambda: P.review_prompt(sb, "r1_targeted_review", 1, venue=prof, scope="full"),
        "review_split_a": lambda: P.review_prompt(sb, "r1_targeted_review", 1, venue=prof, split="a"),
        "review_scoped": lambda: P.review_prompt(sb, "r1_targeted_review", 1, venue=prof,
                                                scope="formatting-writing"),
        "probe": lambda: P.probe_prompt(sb, "r1_probe", 1, venue=prof),
        "audit": lambda: P.audit_prompt(sb, "r1_audit", 1, venue=prof),
        "revise": lambda: P.revise_prompt(sb, "r1_a2_revise", 1, venue=prof, audit=True),
        "integrate": lambda: P.integrate_prompt(sb, "r1_i1", 1, "v1", ["v2", "v3"], venue=prof),
        "rewrite": lambda: P.rewrite_prompt(sb, "r1_w1", 1, venue=prof),
        "judge": lambda: P.judge_prompt(sb, "judge_x_j1", 1, "v1", 1, 2, [], venue=prof),
        "revision_audit": lambda: P.revision_audit_prompt(sb, "r1_revision_audit", 1),
        "revision_repair": lambda: P.revision_repair_prompt(sb, "r1_repair", 1, 3),
    }
    out = {}
    for name, fn in calls.items():
        text = fn()
        # The SANDBOX path first (it may live UNDER the checkout, so normalising
        # the checkout first would fold it into <CHECKOUT> inconsistently), then
        # the checkout's own path, which several blocks embed.
        text = text.replace(str(sb.resolve()), "<SANDBOX>")
        text = text.replace(str(checkout.resolve()), "<CHECKOUT>")
        out[name] = text
    return out


def main(argv: list) -> int:
    checkout = Path(argv[0]).resolve()
    dump = None
    if "--dump" in argv:
        dump = Path(argv[argv.index("--dump") + 1])
        dump.mkdir(parents=True, exist_ok=True)
    texts = render(checkout)
    for name, text in texts.items():
        if dump:
            (dump / f"{name}.md").write_text(text, encoding="utf-8")
        print(f"{name:18} {len(text):>8}  {hashlib.sha256(text.encode()).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Dump `round_run_plan` for a root, from a given checkout (plan-comparison aid)."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list) -> int:
    checkout, root = Path(argv[0]).resolve(), Path(argv[1]).resolve()
    sys.path.insert(0, str(checkout))
    import paper_pipeline as P
    ctx = P.Ctx(root)
    ctx.load()
    out = {}
    for r in range(1, 6):
        try:
            out[r] = [{k: v for k, v in e.items() if k in ("id", "kind", "deps", "stage")}
                      for e in P.round_run_plan(ctx, r)]
        except Exception as exc:          # a plan the root cannot express
            out[r] = f"ERR {exc}"
    json.dump(out, sys.stdout, sort_keys=True, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

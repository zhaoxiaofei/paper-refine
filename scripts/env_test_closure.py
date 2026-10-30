#!/usr/bin/env python3
"""Write the DECLARED test dependencies and their transitive closure.

`scripts/export-test-env.sh` calls this with the test environment's own
interpreter, so the versions recorded in
`env/paper-refine-test.requirements.test.txt` are the ones that environment
actually carries.  Usage:

    python scripts/env_test_closure.py <out-file> [root ...]
"""
from __future__ import annotations

import importlib.metadata as md
import re
import sys
from pathlib import Path

#: The suites are standard-library-only except these two.
DEFAULT_ROOTS = ("python-docx", "openpyxl")


def closure(roots=DEFAULT_ROOTS) -> dict:
    """{lowercased name: (Name, version)} for the roots and everything they need."""
    seen, stack = {}, list(roots)
    while stack:
        name = stack.pop()
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        key = (dist.metadata["Name"] or name).lower()
        if key in seen:
            continue
        seen[key] = (dist.metadata["Name"] or name, dist.version)
        for req in dist.requires or []:
            dep = re.split(r"[ (;<>=!~\[]", req.strip())[0].strip()
            if dep and dep.lower() not in seen:
                stack.append(dep)
    return seen


def main(argv: list) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(argv[0])
    roots = tuple(argv[1:]) or DEFAULT_ROOTS
    seen = closure(roots)
    missing = [r for r in roots
               if r.lower() not in seen]
    if missing:
        print(f"error: root distribution(s) not installed: {', '.join(missing)}",
              file=sys.stderr)
        return 1
    lines = [f"{n}=={v}" for _k, (n, v) in sorted(seen.items())]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"declared test closure: {len(lines)} distribution(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

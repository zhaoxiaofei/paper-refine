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


def requirement_applies(req: str) -> bool:
    """Does this Requires-Dist apply to the CURRENT environment (no extras)?

    `closure` used to take the distribution name from every Requires-Dist line
    and ignore the marker, so an optional-extra requirement (`; extra == "dev"`)
    and a requirement for a platform/Python the environment is not (`;
    python_version < "3"`) both entered the exported closure. The export then
    named packages this environment never installs. `packaging` is present in
    the test environment (and is the standard evaluator); when it is absent the
    old keep-everything behaviour is retained rather than silently dropping
    dependencies.
    """
    try:
        from packaging.requirements import Requirement
    except ImportError:                                          # pragma: no cover
        return True
    try:
        parsed = Requirement(req)
    except Exception:                                            # noqa: BLE001
        return True                       # unparseable: keep it, never drop it
    if parsed.marker is None:
        return True
    try:
        # `extra` is not requested for the roots (`sdist`/`dev` extras are not
        # installed by the test environment), so an extra-gated requirement is
        # out. Other markers are evaluated against the running interpreter.
        return bool(parsed.marker.evaluate({"extra": ""}))
    except Exception:                                            # noqa: BLE001
        return True                       # unknown marker variable: keep it


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
            if not requirement_applies(req):
                continue
            dep = re.split(r"[ (;<>=!~\[]", req.strip())[0].strip()
            if dep and dep.lower() not in seen:
                stack.append(dep)
    return seen


def main(argv: list) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    if argv[0] in ("-h", "--help"):
        print(__doc__, file=sys.stdout)
        return 0
    if argv[0].startswith("-"):
        # Without this branch the first argument was always the output path, so
        # `--help` created a file literally named `--help` in the cwd.
        print(f"error: unknown option {argv[0]!r}\n\n{__doc__}", file=sys.stderr)
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

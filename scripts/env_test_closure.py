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
import os
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


def _norm_dist(name) -> str:
    """PEP 503 normalization: `python_docx` and `python-docx` are one distribution."""
    return re.sub(r"[-_.]+", "-", str(name or "").strip().lower())


def closure(roots=DEFAULT_ROOTS, unresolved: list = None) -> dict:
    """{normalized name: (Name, version)} for the roots and everything they need.

    `unresolved` (when given) receives the name of every DECLARED dependency
    that is not installed. The old walk silently `continue`d on
    `PackageNotFoundError` for roots and transitive dependencies alike, so a
    root that was installed while one of its requirements was not produced a
    "full transitive closure" missing the requirement and still exited 0; the
    recreated environment then failed at import time (F172). `main` passes the
    list and fails the export. Roots are excluded here because `main` already
    reports them as missing roots.
    """
    seen, stack = {}, list(roots)
    root_keys = {_norm_dist(r) for r in roots}
    while stack:
        name = stack.pop()
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            if unresolved is not None and _norm_dist(name) not in root_keys \
                    and name not in unresolved:
                unresolved.append(name)
            continue
        key = _norm_dist(dist.metadata["Name"] or name)
        if key in seen:
            continue
        seen[key] = (dist.metadata["Name"] or name, dist.version)
        for req in dist.requires or []:
            if not requirement_applies(req):
                continue
            dep = re.split(r"[ (;<>=!~\[]", req.strip())[0].strip()
            if dep and _norm_dist(dep) not in seen:
                stack.append(dep)
    return seen


def write_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` atomically: unique sibling .tmp, fsync, replace.

    The dependency record used to be truncated in place (`out.write_text`), so
    an interrupt left a short/empty `requirements.test.txt` that
    `create-test-env.sh` installs as authoritative, and a symlink at the
    destination was written THROUGH. A unique temporary plus `os.replace` makes
    the visible file either the old record or the complete new one, the fsync
    makes the bytes durable, and a symlinked/non-regular destination is refused
    instead of followed (F144). A read-back line count guards a short write.
    """
    path = Path(path)
    if path.is_symlink():
        raise OSError(f"refusing to write through a symlinked destination: {path}")
    if path.exists() and not path.is_file():
        raise OSError(f"refusing to replace a non-regular destination: {path}")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0), 0o666)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if len(tmp.read_text(encoding="utf-8").splitlines()) != len(text.splitlines()):
            raise OSError(f"short write to {tmp}")
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    try:
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


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
    unresolved = []
    seen = closure(roots, unresolved=unresolved)
    missing = [r for r in roots
               if _norm_dist(r) not in seen]
    if missing:
        print(f"error: root distribution(s) not installed: {', '.join(missing)}",
              file=sys.stderr)
        return 1
    if unresolved:
        # Writing the file anyway would present a partial closure as the full
        # one and exit 0; the recreated environment would then fail at import
        # (F172). The declared roots are fine, so name the missing dependency.
        print(f"error: declared dependenc"
              f"{'y' if len(unresolved) == 1 else 'ies'} not installed, so the "
              f"transitive closure would be incomplete: {', '.join(unresolved)}",
              file=sys.stderr)
        return 1
    lines = [f"{n}=={v}" for _k, (n, v) in sorted(seen.items())]
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_atomic(out, "\n".join(lines) + "\n")
    except OSError as e:
        print(f"error: could not write {out}: {e}", file=sys.stderr)
        return 1
    print(f"declared test closure: {len(lines)} distribution(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

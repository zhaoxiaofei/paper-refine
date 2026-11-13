#!/usr/bin/env python3
"""Read a split source bundle as ONE logical source text / AST.

`paper_pipeline.py` and `paper_docx_format.py` are thin loaders: their code lives
in `<name>_parts/pNN_*.py` and is executed, in order, in the loader's globals.
Tests that inspect the source (string contract checks, AST walkers) must see the
whole bundle, not just the loader. This module is the one place that knows the
layout.
"""
from __future__ import annotations

import ast
import importlib.util
import shutil
import sys
from pathlib import Path


MODULE_FILES = ("paper_pipeline.py", "paper_docx_format.py",
                "paper_redlines_adapter.py", "paper_qwen_agent.py",
                "paper_dots_agent.py", "paper_model_agent.py", "paper_dsh_runtime.py",
                "docx2pdf.sh", "docxcompare.sh")
ASSET_DIRS = ("paper_pipeline_parts", "paper_docx_format_parts", "agent-common", "paper-skills")


def bundle_files(path) -> list:
    """The loader followed by its ordered parts (the loader alone when unsplit)."""
    path = Path(path)
    parts_dir = path.with_name(path.stem + "_parts")
    files = [path]
    if parts_dir.is_dir():
        files.extend(sorted(parts_dir.glob("p[0-9][0-9]_*.py")))
    return files


def source_text(path, **read_kwargs) -> str:
    """The logical source text: loader + every part, separated by newlines."""
    chunks = []
    for p in bundle_files(path):
        try:
            chunks.append(p.read_text(**read_kwargs))
        except OSError:
            continue
    return "\n".join(chunks)


def bundle_tree(path) -> ast.Module:
    """One AST module whose body concatenates the loader's and parts' bodies."""
    body = []
    for p in bundle_files(path):
        body.extend(ast.parse(p.read_text(encoding="utf-8", errors="replace")).body)
    return ast.Module(body=body, type_ignores=[])


def copy_bundle(src_dir, dst_dir) -> None:
    """Copy the loader(s), the optional siblings and their parts directories."""
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in MODULE_FILES:
        if (src_dir / name).is_file():
            shutil.copy2(src_dir / name, dst_dir / name)
    for name in ASSET_DIRS:
        src = src_dir / name
        if not src.is_dir():
            continue
        dst = dst_dir / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))



def load_bundle(name, path):
    """Import an entry point by filename, including its bundled dependencies."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

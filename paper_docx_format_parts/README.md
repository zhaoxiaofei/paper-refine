# `paper_docx_format_parts/` — the OOXML formatter's implementation

`paper_docx_format.py` is a thin loader. It executes these files **in filename
order** in its own module globals, so every public and private name the pipeline
and the tests use remains a normal module attribute. Every file is under 10,000
lines.

| part | responsibility |
|---|---|
| `p00_core.py` | namespaces, policy defaults, regexes, XML primitives, Zotero field inventory, styles/emphasis |
| `p01_text_rules.py` | text-level rules: numbers, claim strength, citations, references, outline |
| `p02_layout_edit.py` | text-span splicing, display/caption blocks, hygiene, image geometry, Zotero parity/refresh, bibliography repair |
| `p03_report_cli.py` | package analysis/scanning, fixers, template conformance, LaTeX/PDF checks, layout integrity, CLI |

**Packaging:** `setup`, `sync-code` and every stage sandbox copy this directory
together with the loader (`python paper_docx_format.py ...` resolves the parts
from beside the script). A missing directory is reported, never silently
degraded.

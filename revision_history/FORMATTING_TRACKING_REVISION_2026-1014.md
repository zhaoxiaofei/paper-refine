# 2026-10-14 revision — caption formatting, redline fidelity, lone divisions

Operator report, four items:

1. one figure caption renders with inconsistent vertical space (1-line and
   1.5-line spacing between its lines);
2. multi-paragraph figure captions should be avoided;
3. the tracked-changes `.docx` seems to mark far more words changed than the
   revision really made;
4. a tracking copy missed a soft line break (SHIFT+ENTER in Word);
5. sometimes a paragraph consists of only one sentence — avoid that (which
   generalises to: a container that divides at all divides into more than one
   part, at every level of the outline).

This file records what was found and what the repository revision does about
it. The two published packages were inspected read-only; they were not
regenerated and nothing was committed.

## What was inspected

* `manuscript-postgrad-data/cnb-28to29-1014-1940-6acf1fa/final_clean_version_cnb-28to29-1014-1940-6acf1fa/`
  (`cnb-29-2-mainText-cd05d42.docx` and its `FORMAT_FIX` report);
* `manuscript-postgrad-data/neohet-11to12-1013-1940-6acf1fa/final_clean_version_neohet-11to12-1013-1940-6acf1fa/`
  (`neohetero-13-2-mainText…docx`, `…-13-3-supplementaryMaterial…docx` and the
  `FORMAT_FIX` report);
* the tracking copies `round1_winner/*.tracking-original.docx` and
  `tracking/manifest.json` of both roots.

## 1–2 — the caption problems (evidence)

The published CNB main text (byte-identical to the round-1 winner) keeps the
author's hand-split legends:

| paragraph | what it is | own spacing | effective line spacing |
|---|---|---|---|
| p173 `Fig. 2 \| …` | legend label | `before/after 200, line 240` | single |
| p174, p175 | the SAME legend, two more paragraphs (first-line indent 480) | `200/200/240` | single |
| p177 `Fig. 3 \| …` | legend label | `200/200/240` | single |
| p178 | the SAME legend, second paragraph (first-line indent 480) | **none** | **360 (1.5) — the document default** |

So `Fig. 3`'s caption carried lines at single spacing and lines at 1.5 spacing —
the operator's item 1 — and `Fig. 2`/`Fig. 3` were three-/two-paragraph captions
(item 2). In the NeoHetero main text the same shape appears: Figures 1–4 are
label (Caption style, direct `200/200/240`) + one continuation paragraph (body
style, no direct spacing), and in the supplementary file Figures S1–S3 are two
paragraphs each.

Three further formatting defects fell out of the same inspection:

* the scan/fixer recognized only `Fig(ure) \d+` labels, so **`Figure S1.` /
  `Table S1.` / `Supplementary …` captions were never normalized**: in the
  NeoHetero main text Figures 1–4 got `200/200/240`, while `Figure S1–S3` and
  every table caption kept the body style's `120/240` spacing (and the
  supplementary file's captions kept whatever the author used);
* the supplementary file's **first legend carried the template's front-matter
  `AuthorList` style** while its two siblings carried no style at all — one
  caption renders differently from the others;
* the continuation paragraphs carry their own indents/styles
  (`firstLine=480`, body style), so a "single" caption renders as two visually
  different paragraphs.

Secondary effect of the same blind spot: the pipeline's text model classifies
legends by `LEGEND_RE`, so those continuation paragraphs were read as BODY text
— they inflated the section's word count and took the body sentence-length bar
instead of the legend bar. Merging them into the label paragraph (and the wider
label vocabulary) puts them back inside the legend.

## 3–4 — the tracked-changes problems (evidence and cause)

**Over-marking (CNB).** The tracking manifest says the pair was tracked with
`docx-trackdiff` (the MCP `docx-compare` server did not answer and
`python-redlines[docxodus]` was skipped: *"adapter missing:
…/cnb-…/paper_redlines_adapter.py"* — the adapter ships next to the orchestrator
but `setup` did not copy it into the root). On that pair the file marks **319
inserted + 305 deleted words (624 total) where the real change is 27 + 57 = 84
words**; the dominant contributor is one paragraph (`REV[95]`, the HG008
evaluation) marked as **230 words deleted + 239 inserted for a ~10-word edit**.

Cause: `docx-trackdiff` diffs a paragraph word by word only when it can map the
diff onto the paragraph's runs. A Word paragraph carries
`w:lastRenderedPageBreak` inside its text run (every page-leading paragraph
does), and a run that is not plain `rPr`+`t` is treated as ONE atomic item, so
the rewrite fails and the tool falls back to *delete the whole paragraph +
insert the whole paragraph*. Content that moves between paragraphs is likewise
shown as delete+insert. Reproduced with the tool's own debug output
(`GRANULAR FAIL atomic-too-long`).

**Soft line breaks (NeoHetero).** The tracking copy of the NeoHetero main text
has **zero `<w:br/>`** where the base and the revised document each have two:
the correspondence block's two SHIFT+ENTER breaks are gone. Cause: that run used
the built-in OOXML writer (the same root had no `docx-trackdiff` in its Python
at all — see its manifest), and that writer rebuilt a changed paragraph from
plain text, dropping every non-text inline element.

## The MCP compare server ("did not answer initialize()")

Two deployment defects, both silent, made the first-choice `docx-compare`
backend dead on this machine (and the `docx-converter` MCP renderer with it):

1. **The servers' npm dependencies were never installed.** Every copy of
   `mcp-docx-compare/` and `mcp-docx-converter/` (the repo's and the configured
   `/mnt/c/.../zxf-cnv-paper-postgrad/` ones) had no `node_modules/`, so
   `node index.js` exited with `ERR_MODULE_NOT_FOUND: Cannot find package
   '@modelcontextprotocol/server'` before it read stdin. The pipeline discarded
   the server's stderr (`stderr=subprocess.DEVNULL`), so the manifest recorded
   only "the MCP server did not answer initialize()".
2. **The compare server's companion script was missing.** `index.js` runs
   `docxcompare.sh`, resolved as `../docxcompare.sh`, `./docxcompare.sh`, then
   PATH. `install_skill.sh` copied only the `mcp-*` directories, so the
   configured copy had no `docxcompare.sh` anywhere → even a server with
   dependencies would fail EVERY tool call with `spawn docxcompare.sh ENOENT`
   (the converter's `docx2pdf.sh` happened to sit in the parent directory).

Fixed and verified: `npm ci` in both server directories (repo and configured
copies); `docxcompare.sh` installed beside them; a real `compare_docx` call on
the CNB main-text pair now returns Word's own tracked-changes file in ~11 s
(fidelity 121 marked vs 123 minimal words — not over-marked, like the docxodus
engine). The repo revision makes the class visible and the deployment durable:

* `mcp_stdio_tool_call` captures the server's stderr and reports it with the
  exit code (`... did not answer initialize(); the server exited with code 3;
  stderr: ERR_MODULE_NOT_FOUND ...`) instead of the bare handshake message;
* `mcp_server_unusable_reason(name)` (which `mcp_server_configured` now wraps)
  also checks a Node server's declared dependencies (`node_modules` up the
  tree) and the shipped servers' companion scripts (`docxcompare.sh` /
  `docx2pdf.sh` beside `index.js`, in its parent, on PATH, or via
  `DOCXCOMPARE_SH`/`DOCX2PDF_SH`); the redline manifest's skipped-backend row
  and the renderer list now carry that reason;
* `install_skill.sh` installs the source without `node_modules`, runs `npm ci`
  at the destination, and installs the companion script `0755`, so the
  deployed copies start.

## 5 — one-sentence paragraphs

The final packages contain single-sentence narrative paragraphs, e.g. in the CNB
main text p42 (18 words), p43 (35), p50 (38), p65 (23), p67 (44) and in the
NeoHetero main text p20/p21/p22 ("First/Second/Third, …" 10/32/25 words). No
scan rule existed for the class. (Neither package currently has a section that
holds exactly one subsection — the generalised case — but nothing enforced it
either.)

## The revision

`paper_docx_format.py`

* the caption/legend **label vocabulary** now covers the supplementary and
  extended-data forms (`Figure S1.`, `Supplementary Fig. 4:`, `Table S1 …`) and
  the same words the display rules already recognized;
* a shared **caption BLOCK** definition (`caption_block_ranges`): a label plus
  the paragraphs that continue it, inside the venue's own figures/tables area
  (`display_area_kinds`; the headings now accept the supplementary prefix).
  Table-cell/text-box paragraphs are excluded via `container_spans`;
* `FMT-T2a`/`FMT-T2b` now check **every paragraph of the block**, so the
  continuation that inherits 1.5 spacing is a row and the fixer unifies the
  spacing across the caption;
* new `FMT-T2c`: a caption split across paragraphs — the fixer **merges** the
  continuation paragraphs into the label paragraph (every run travels verbatim;
  moved runs get an explicit bold/italic/size pin only where the label's style
  would change them; the only added bytes are separator spaces), and the
  fixer's verifier is told the joins (`meta["caption_joins"]`,
  `verified.caption_joins`) so text identity is still proven. A block carrying a
  drawing, a text box, a tracked change or a section break is left alone and the
  row is `fix=editorial` for the revision arms;
* new `FMT-T2d`: a caption carrying a paragraph style its sibling captions in
  the same area do not (the supplementary file's `AuthorList` first legend) —
  the minority is aligned with the majority; a tie reports nothing;
* new `FMT-T9k` (finding): a narrative paragraph built from ONE sentence
  (body/abstract, 5–45 words), with end-matter sections, statement shapes,
  acronym lists, keywords, captions and table cells exempt;
* new `FMT-T10f` (finding): a heading whose section holds exactly ONE
  subsection — the same "lone division" rule one level up.
* the mega-paragraph rule (`FMT-T9i`) no longer fires on legends: a legend is
  ONE paragraph by the caption rule, and its length is the venue's M18
  word-budget question — "split it at the natural boundary" is wrong advice
  there (the merged captions are 250–280 words and were being reported).

`paper_pipeline.py`

* the `redlines` backend now runs `python-redlines[docxodus]` **in process**
  (temp cache retry included), so a root without the adapter file no longer
  loses that engine; `setup` copies `paper_redlines_adapter.py` into the root
  with the other modules;
* new `redline_fidelity(base, revised, out)`: the words a redline marks
  (`w:ins`/`w:del`) against the least a faithful redline needs (paragraph
  aligned, word level). Under `--tool auto` an over-marking backend is passed
  over for the next one and the least-marked result is kept; an explicit
  `--tool`/`--redline-cmd` choice is honoured with the caveat recorded.
  `manifest.json` carries `fidelity` per attempt and the readme lists
  over-marked files under Caveats;
* `builtin_tracked_changes` / `_replace_para` rewritten: the diff is walked op
  by op, only the changed text is rewritten (every run keeps its `rPr`), and
  non-text inline elements (soft line breaks, tabs, field chars) keep their
  places — accepting every change reproduces the revised paragraph and
  rejecting every change reproduces the base paragraph. A paragraph that cannot
  be split piecewise falls back to whole-paragraph markup that carries the
  revised paragraph's own XML (nothing is dropped);
* the writing rules (`LANGUAGE_PASS_RULE`, the revise prompt and the skill's
  `edit_rules.md`) now state the paragraph/section shape rule and name
  `FMT-T9k`/`FMT-T10f`/`FMT-T2c` in the post-step rescan sentence.
* the stage regression check attributes the text-model side effect of the
  merge: `_scan_rule_delta` records the rules the format fixer's own scans
  gained, and `scan_regression_problems(..., fixer_reclassified=...)` reports
  those as a warning that names the FORMAT_FIX artifact (the caption's text is
  now READ as a legend, and the review still disposes the rows) instead of
  failing a stage that changed no text — the trap a legacy root resumed with
  this revision would otherwise hit. Growth inside a family the base already
  had stays a warning, and a genuinely new family stays an error.

Tests (all offline):

* `.paper_test/test_docx_format_5_caption_blocks.py` (new) — the caption-block
  scan rows, the merge (text identity, joins, bold pinning, refused blocks),
  the style alignment, the table-cell exclusion;
* `.paper_test/test_redline_fidelity.py` (new) — soft-break preservation,
  accept/reject identity, the page-break-run paragraph, the over-marking flag,
  the chain's fidelity record, the adapter ship/resolve;
* `.paper_test/docx_format_lib.py` — fixtures/styles for both new suites and
  `test_lone_division_rules` (FMT-T9k/FMT-T10f, registered in PART 2);
* `.paper_test/README.md`, `README.md` and the module docstring document the
  new rules; the skill-doc appendices were re-synced (the verbatim appendix
  check in `test_acronym_longform.py`).

## How to verify

```bash
python3 .paper_test/run_all.py -j 24                       # the whole suite
python3 .paper_test/test_docx_format_5_caption_blocks.py   # the caption work
python3 .paper_test/test_redline_fidelity.py               # the redline work
```

Against the two real packages (read-only inputs, output in /tmp):

```bash
python3 paper_docx_format.py scan <final_clean_version dir> --json /tmp/scan.json
python3 paper_docx_format.py fix  <mainText docx> --out /tmp/fixed.docx --json /tmp/fix.json
```

Re-measured on 2026-10-14 with this revision:

* CNB main text: the two multi-paragraph captions merge (`caption_joins: 2`,
  `text_identical: true`, schema valid, `mechanical_findings 4 -> 0`);
* NeoHetero main text: four captions merge, all captions (including `Figure
  S1–S3` and the tables) carry `240/200/200`, `text_identical: true`;
* NeoHetero supplementary file: three captions merge and the first legend's
  `AuthorList` style is aligned away;
* the CNB and NeoHetero tracking pairs now resolve to
  `python-redlines[docxodus]` (120/108 marked words vs 123/114 minimal — not
  over-marked) where the run had 624 marked words (CNB) and lost soft breaks
  (NeoHetero); the built-in writer's own output marks 123/123 and 119/114 and
  keeps the soft breaks with accept/reject identity.

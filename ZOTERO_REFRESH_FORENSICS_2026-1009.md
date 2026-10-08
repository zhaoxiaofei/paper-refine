# Why the Word/Zotero refresh rewrote the citations — and what the repo now does about it

Forensics on the two read-only CNB DOCX files (nothing in the audited trees was modified):

* `…/cnb-23to24-1008-0413-6f541c1/final_clean_version/cnb-24-2-mainText-c27c42e.docx` — the
  pipeline's CERTIFIED output;
* `…/cnb-23to24-1008-0413-6f541c1/final_manual_clean_version/cnb-24-2-mainText-c27c42e.docx` —
  the author's copy after **Zotero → Refresh** in Word.

Both are the same document lineage: **124 live `ZOTERO_ITEM` citation fields with the same
`citationID`s, one bibliography field, 46 distinct cited items**, and the same
`ZOTERO_PREF_1` document preferences stored twice.

## 1. What a Zotero field actually is

A live citation field has two halves:

* the **instruction** (`ADDIN ZOTERO_ITEM CSL_CITATION {…}`) — the item list, each item's
  embedded `itemData` (title, creators, date, DOI) and the *cached* markers Zotero last wrote
  (`properties.formattedCitation`, e.g. `\super 3,39\nosupersub{}`);
* the **result** runs — the text a reader sees (`3,39`).

The bibliography is one more field whose RESULT is the whole reference list. **Refresh** in Word
re-runs the citation processor: it walks the document, derives each item's number from the order
in which the items are first cited, rewrites every marker, reorders the reference list, and
re-renders the entries in the CSL style the document's preference store names. It does not check
whether that changes what the submission said — it simply makes the file self-consistent.

## 2. What the certified file carried (measured)

| measurement | `final_clean_version` (certified) |
|---|---|
| citation fields / distinct items / bibliography entries | 124 / 46 / 46 |
| markers whose number is **not** the cited item's rank in the document's own citation order | **79 of 124** fields |
| bibliography entries sitting at a rank that describes **another work** | **15** |
| example | the 2nd distinct citation shows `39` (the item's rank is 4); the CNP sentence cites Zarrei as `37` (rank 38); COSMIC shows `27` (rank 28) |
| Zotero style stores | **two, conflicting**: `word/settings.xml` docVars → `nature` (written by Zotero 6.0.37); `docProps/custom.xml` → `nature-biotechnology` (written by Zotero 10.0.3) |

So the certified package was already internally inconsistent: its numbered markers and its
reference list did not agree with its own citation order, and its two style stores named
different CSL styles. Nothing in the pipeline looked at either fact.

## 3. What the refresh did

After **Zotero → Refresh** in Word:

* the bibliography was re-derived in the correct citation order (0 mismatched entries);
* **111 of 124 markers were rewritten** to the new numbering (e.g. the same field went
  `3,39` → `3,4`; the CNP sentence's item moved from 37 to 38);
* **3 fields kept their old numbers** and therefore now point at the wrong reference —
  precisely the citation errors the external audit reported: `COSMIC profiles²⁷` (27 is SafeMut
  in the new list; COSMIC is 28), `(hg19)³⁷` (37 is now SCEVAN; Zarrei is 38), and
  `as the relevant data grow³⁹,⁴⁰` (should be 4,41 — the same field also leaves entry 41
  uncited);
* the **reference formatting changed**: the entries were re-rendered in the other style
  (`1.Chen, C. …` instead of `1. Chen, C. …`; BWA-MEM as `Li, H. … (2013).` instead of
  `Preprint at arXiv:1303.3997 (2013)`), which is the `nature` vs `nature-biotechnology`
  conflict above.

In short: **the refresh fixed most of a stale cache and left residue.** The errors the audit saw
were not caused by the refresh inventing anything — they are the fingerprint of a document whose
live-field cache had been stale since before it was certified, plus a style store that says two
different things.

## 4. Why the pipeline could not see it

* The Zotero contract (`zotero_field_report`, `zotero_field_continuity_problems`) verifies that
  fields are PRESENT, structurally sound (begin/separate/end, parseable JSON, unique
  citationIDs), and that a stage does not delete them — and it explicitly allows a changed field
  as "an edited field". It never compared a marker's number with the document's citation order,
  never compared a bibliography entry with the item it is supposed to be, and never looked at the
  style stores at all.
* The pipeline *preserves* field results byte-for-byte (by design: Word/Zotero regenerate them),
  so a stale cache travels through every round untouched — and the `REPLACEMENT_LEDGER` even
  recorded "124 live Zotero citation fields preserved" as a success.
* The reference checks that existed (M10, the identifier lookups) read the bibliography TEXT; they
  cannot tell that entry 27 is the wrong work for the sentence that cites 27.

## 5. What the repo now does (implemented, no commit yet)

**`paper_docx_format.py` — FMT-Z1..Z5, offline, no library needed** (`zotero_citation_state`,
`zotero_parity_rows`), because every citation field embeds its own `itemData`:

| row | meaning |
|---|---|
| `FMT-Z1` | a marker's number is not the cited item's rank in the document's own citation order (a stale marker the refresh rewrites) |
| `FMT-Z2` | the bibliography entry at an item's rank describes a different work (the cached bibliography order is stale) |
| `FMT-Z3` | one item renders two numbers; a number outside 1..N; an entry that is never cited |
| `FMT-Z4` | the field's stored marker disagrees with the runs a reader sees (a half-updated document) |
| `FMT-Z5` | the package carries two conflicting Zotero style stores |

They run in the normal scan (`analyse_document`/`analyse_package`), every row is `fix=manual`
and `protected=true` (a field result is never edited by the tools), and a new CLI runs them on a
single file — **run it after every refresh**:

```bash
python3 paper_docx_format.py zotero-check final_clean_version/cnb-24-2-mainText-….docx
# → 4 FMT-Z1 + 1 FMT-Z3 + 1 FMT-Z5 on the refreshed copy; 60 FMT-Z1 + 1 FMT-Z5 on the
#   pre-refresh copy; CLEAN on the neohetero manuscript (which was never hand-refreshed)
```

**Version-to-version gate.** `zotero_report_for_docx` carries the rows and
`zotero_field_continuity_problems` now makes a stage that **introduces** a high-severity parity
row a hard ERROR, while a refresh that clears them is a recorded repair — so the pipeline
cannot silently accept a version whose numbering was rewritten.

**Sweep M36 + prompts.** `M36 — Zotero live-field refresh parity` is a required review coverage
row with its own artifact (`review/artifacts/M36_zotero_parity.md`); the review/audit/revise/
integrate/rewrite prompts say exactly what a session may and may not do (never edit a field;
refresh in Word/Zotero, re-run `zotero-check`, and only then flatten). Discovery proposals now
start at M37. The judge's frozen map is unchanged.

**The safe author workflow** (also written into `AGENT.md` and the sweep):

1. `python3 paper_docx_format.py zotero-check <docx>` on the current file;
2. if it reports rows: fix the style stores to ONE style (the venue's), refresh in Word, and
   re-run until clean (a field the refresh leaves behind must be repaired in Word);
3. only then may the fields be flattened for the submission copy (`unlink_zotero_fields`);
4. **never flatten a stale document** — that freezes the wrong numbering for the journal, and
   any later refresh of a copy that still has live fields will renumber everything again.

## 6. What a human still owns

The repo can now detect and gate the whole class, but it cannot re-render Zotero fields: the
refresh (and the choice of ONE CSL style for this manuscript) is an author action. On the CNB
file specifically, the three residual fields must be refreshed/repaired in Word, entry 41
(Erickson) either cited or dropped, and the style conflict resolved in favour of
`nature-biotechnology` before the numbering can be trusted in the submitted PDF.

# Design issues in the NBT round-based revision pipeline

**Subject.** `/tmp/repo` — the NBT round pipeline as of `7d19d80` (2026-09-22).
**Question.** Which *design* issues remain in `nbt_pipeline.py`, `nbt_docx_format.py`,
and the two skills — especially mismatched objectives across roles, non-convergence,
slow / local-optimum search, and judges that cannot see grammar — rather than
missing mechanical capabilities.
**Status.** Read-only audit. No pipeline or manuscript file was modified.

This document is the full issue list. It is organised around the failure classes
the operator named (prompt/score mismatch, auditor≠reviewer, non-convergence,
slow search, local optima, judge/agent mismatch, ignored grammar), then a short
redesign note.

Line numbers refer to this tree (`nbt_pipeline.py` 17,819 lines;
`nbt_docx_format.py` 3,046 lines).

---

## 0. Verdict in one page

The 2026-09-22 “one shared rule set” patch (`SHARED_DECISION_BLOCK` plus
`.nbt_test/test_agent_consistency_2026_0922.py`) did **not** close the
objective-mismatch. It injected a common block *under* role directives that
still say they override it. The consistency test only checks that the shared
block is **present**, and one of its checks is a tautology
(`"M21" in nb.__doc__ or True`).

| id | Failure class | What happens | Why it cannot converge |
|----|---------------|--------------|------------------------|
| D1 | Conflicting objectives | Reviser / language-pass *insert* em-dashes; M20 / judges *penalize* them | Oscillation, not a fixed point |
| D2 | Auditor ≠ reviewer | Auditor may drop `F-*` and add `AU-*`; reviser obeys the auditor; judges re-derive their own list | A “fix” for one role is a defect for another |
| D3 | Judges ignore grammar | Writing/formatting capped at ±1; J3 is optional; shared grammar is scored 0 | Syntax/grammar cannot move the champion |
| D4 | Merge-into-base | Integrator keeps the base, freezes shared defects, prefers the incumbent on ties | Local optimum around A1 |
| D5 | Too much scoring, too little targeting | ~58 sessions / 2 rounds; 24 of round 1’s 33 are judges; rewrites run *before* the review | Cost is in pairwise judging, not in fixing the known list |
| D6 | Scores incomparable across rounds | New panel, new field, new review every round; documented as not comparable | You cannot plot a learning curve |
| D7 | No stopping rule | Fixed `R=2`, default `--stop-after-no-progress 0` | Extra round of scoring even after no-progress |

These are design issues, not missing features. Several residual-ledger
workstreams (W-01–W-12) were marked implemented; the contradictions below
are what that implementation left in place.

---

## 1. Different prompts, different scoring functions

The canonical example (judges penalize em-dash, reviser favors em-dash) is
implemented as several *partial* policies that do not compose.

### D1.1 Nested-paren fix introduces the dash that M20 then forbids

Finding-tier rule `FMT-T8b` tells the reviser to un-nest with an **em dash**:

```
nbt_docx_format.py:1638-1641
    rows.append({"rule": "FMT-T8b", "severity": "medium",
                 "evidence": text[start:end][:110],
                 "detail": "parentheses inside parentheses read badly; move the "
                           "inner item out (comma or em dash) or restructure the "
```

`FMT-T8b` is in `FINDING_TIER_RULES` (`nbt_docx_format.py:595-608`). The
reviser **must** dispose it.

The same reviser is then told, under M20:

```
nbt_pipeline.py:1853-1856  (M20_REVISE_RULE)
    Fix the EDITORIAL rows yourself: rewrite parenthetical em-dashes as
    commas/parentheses, make the quotation style uniform, ...
```

Cycle: un-nest with an em-dash → density exceeds
`max_em_dashes_per_1000 = 2.0` (`nbt_docx_format.py:74`) → rewrite dashes as
parentheses → nested parens return. That is a two-cycle oscillator, not a
policy.

### D1.2 Scanner vs skill disagree on whether em-dash density is a finding

`FMT-P1` (em-dash density over cap) is **not** in `FINDING_TIER_RULES`, so the
code-side scan marks it `advisory` (`nbt_docx_format.py:2155-2160`,
`tier_of()` at `:611-613`).

`nbt-skills/nbt-review/references/sweeps.md:637-639` says the opposite:

> mixed straight/curly quotation marks, a spaced hyphen used as a dash, or
> **em-dash density above the user's cap → finding**

The auditor is instructed to attack only **finding-tier** scan rows
(`AUDIT_DIRECTIVES` task 2, `nbt_pipeline.py:3138-3144`). An advisory
`FMT-P1` the reviewer closed as “editorial preference” is invisible to the
auditor, while a reviewer who follows `sweeps.md` files it as `F-*`. Same
row, two agendas.

### D1.3 Language pass favors the dash the judges then treat as noise

`LANGUAGE_PASS_RULE` L9 is “stiff/translated phrasing and word order (keep
the meaning, **make it flow**)” (`nbt_pipeline.py:3669`). That is the
instruction under which current models insert em-dashes. L11 is
“typos/punctuation”.

The rewrite arm is simultaneously told **not** to fix M20 editorial rows
(`M20_REWRITE_RULE`, `nbt_pipeline.py:1866-1871`: “REPORTED here, not
fixed”).

The judge’s writing rubric Q11 then scores “a spaced hyphen used as a dash,
mixed quotation marks” as writing, and writing is **minor-only, cap ±1**
(`WRITING_RUBRIC` at `nbt_pipeline.py:11551-11572`; `TIER_CAPS` at
`:1410-1411`).

| Role | Em-dash objective |
|------|-------------------|
| Scanner `FMT-T8b` | Insert them (finding-tier) |
| Language pass L9 | Insert them (“flow”) |
| Rewrite M20 | Leave them (report only) |
| Reviser M20 / `sweeps.md` | Remove them |
| Judge Q11 + cap | Notice them, then throw the point away |

### D1.4 Q1–Q3 of the “writing” rubric are not writing

```
nbt_pipeline.py:11551-11572  (WRITING_RUBRIC)
  Q1  the sentence's factual premise is contradicted by the data or by another sentence
  Q2  a formal-logic slip ...
  Q3  a logic jump ...
  Q10 grammar ...
  Q12 segmentation ...
  ... The tier is minor-only, so it can separate two otherwise equal packages
      by at most one point
  ... Q1-Q11 correspond one-to-one to the eleven checks of the language pass
```

A **factual contradiction** (Q1) and a **logic error** (Q2/Q3) are
correctness, often Critical. Parking them on the writing rubric forces a
well-behaved judge to score a wrong claim as a ±1 minor. A reviewer following
`sweeps.md` J3 files the same sentence as category 0/1, class `correctness`.
The panel and the reviser are then optimizing different functions of the
same sentence.

Q12 (segmentation) has **no** L12. The language pass is L1–L11
(`LANGUAGE_PASS_RULE`, `nbt_pipeline.py:3658-3672`;
`language_pass_report()` wants `L1..L11` at `:11577`). The judge scores a
12th check the producers never run.

The consistency test asserts the *presence* of the sentence
`"Q1-Q11 correspond one-to-one to the"`
(`.nbt_test/test_agent_consistency_2026_0922.py:156-157`), so the mismatch
is in the string the test greps for: the test is green by construction.

---

## 2. Auditor and reviewer run different agendas

### D2.1 Control flow: drops delete findings the reviser never sees

The reviewer’s job is “identify, do not fix”, with discovery D0–D5, and
J1–J4 *“may be prioritized”* (`nbt-skills/nbt-review/SKILL.md` hard rule 4).

The auditor’s job (`AUDIT_DIRECTIVES`, `nbt_pipeline.py:3092-3181`):

1. confirm or **drop** every frozen `F-*`
2. **promote** the reviewer’s `OK` closures of finding-tier rows to `AU-*`
3. never re-run discovery

Then `apply_audit_to_findings()` **deletes** dropped ids from the list the
reviser sees (`nbt_pipeline.py:11795-11808`):

```
(dropped if str(f.get("id") or "").strip() in drops else kept).append(f)
return {..., "effective": kept + adds}
```

So a reviewer’s `F-031` (nested parens) that the auditor drops is a non-fix
for the reviser. A reviewer’s `OK` that the auditor promotes to `AU-004` is
a *new* defect the reviser must introduce a change for.

The reviser is told explicitly (`revise_prompt` audit block,
`nbt_pipeline.py:4371-4377`):

> Act on the AUDITED list: a dropped finding is NOT yours to re-litigate
> (re-opening one requires new evidence …); every `AU-*` finding is a
> normal finding you must resolve.

### D2.2 Judges never see either list

The judge re-runs `$nbt-review` on the blinded target and is told
(`JUDGE_DIRECTIVES`, `nbt_pipeline.py:3769-3777`):

> RESTRICTED TO THE FROZEN SWEEP SET -- mechanical sweeps M1-M17 and
> judgment passes J1-J4 **ONLY**
> Do NOT run the discovery phase D0–D5 and do NOT propose new sweeps

`ADOPTED_SWEEPS_BLOCK` (appended *later*, `nbt_pipeline.py:2000-2024`)
requires M21–M24. Directives “override anything below where they conflict”
(`JUDGE_DIRECTIVES` header, `:3729`). The judge who obeys the first
instruction skips the checks the reviser was scored against.

A fix that is correct under the audited list is therefore often a no-op or
a regression under the judge’s independently derived list. That is the
“fix in the eye of the reviewer is a bigger defect in the eye of the
auditor/judge” mechanism, and it is in the control flow, not in model noise.

### D2.3 The class tables do not agree on whether `writing` exists

| Source | Priority order | Where grammar goes |
|--------|----------------|--------------------|
| `BASIS_TIERS` / `SHARED_DECISION_BLOCK` (`nbt_pipeline.py:1399-1400`, `:1962-1968`) | … completeness > **formatting > writing** | `writing` (minor) |
| `JUDGE_DIRECTIVES` “PRIORITY ORDER” (`:3899-3901`) | … completeness > **formatting** (no writing) | omitted |
| `sweeps.md` CLASSIFICATION (`:36-47`) | … completeness > **formatting** (no writing) | category 2 → consistency / correctness / **formatting** |

A grammar error classified as `formatting` by the skill, `writing` by the
shared block, and “wording preference = 0” by the judge scale (D3.4) is
three different numbers.

`DEFECT_CLASS_RULE_TEMPLATE` (`nbt_pipeline.py:2072-2078`) maps category 2
four ways (consistency / correctness / formatting / writing). `sweeps.md`
maps it three ways and never mentions the `writing` class. The skill is
what the reviewer and the judge are told to follow
(`JUDGE_DIRECTIVES` task 1: “read the skill's SKILL.md and
references/sweeps.md”).

---

## 3. Judges systematically ignore semantic / syntax / grammar errors

Three independent mechanisms, any one of which would be enough.

### D3.1 Cap: writing cannot decide a comparison

```
nbt_pipeline.py:1404-1413
TIER_ROW_WEIGHTS = {..., "formatting": {"minor": 1, "major": 1, "critical": 1},
                    "writing":     {"minor": 1, "major": 1, "critical": 1}}
TIER_CAPS = {..., "formatting": 1, "writing": 1}
MINOR_ONLY_TIERS = ("formatting", "writing")
```

Ten grammar rows still contribute 1 point. `|score| ≥ 3` requires a
MAJOR/CRITICAL item *outside* those tiers (`JUDGE_DIRECTIVES`:3880-3885;
`judge_basis_problems()` `:12497-12500`). Grammar cannot crown a version.

The derived-score enforcer repeats it (`nbt_pipeline.py:12558-12561`):

> a per-tier cap applies, so formatting/writing can never exceed +-1

### D3.2 Shared defects are scored 0

Scores are pairwise and relative. If every field member still has the same
subject–verb error (the typical case — see D4.2), both ledgers are empty
and the score is 0. The prompt says an all-zero sheet is “often the honest
sheet” (`JUDGE_DIRECTIVES`:3846-3848).

Integration class (d) *defines* shared defects as not portable
(`INTEGRATE_DIRECTIVES`:3245-3249). They therefore persist into every
member of the field, and the panel cannot see them.

### D3.3 J3 is optional

`SKILL.md` hard rule 4: “Only judgment passes J1–J4 may be prioritized.”
A judge under token pressure skips J3 (Writing quality, logic, and
overclaiming — the only sweep that names “Semantic/grammatical/syntactic
errors”, `sweeps.md:676-688`).

There is no postcheck that a grammar artifact exists — only that
`checks["J3"]` has *some* disposition string (`clean` / `findings` /
`unable`). `unable -- skipped` satisfies `judge_coverage_problems()`
(`nbt_pipeline.py:12439-12480`).

### D3.4 Private rule still zeroes “wording preferences”

The same judge prompt still contains the pre-shared-block rule
(`JUDGE_DIRECTIVES`:3849-3851):

> Cosmetic-only differences (spacing, font choice, ordering of identical
> content, wording preferences that do not change meaning) are 0 -- they
> are worth no points in either direction. Judge CONTENT, not style.

“Wording preferences that do not change meaning” **is** grammar,
punctuation, and prose-flow. Directives override the shared block that
says those are counted minor rows (`SHARED_DECISION_BLOCK` D1, D3).

The consistency test never diffs role-private text against the shared
block; it only asserts the shared block occurs once
(`.nbt_test/test_agent_consistency_2026_0922.py:95-113`).

### D3.5 Q1–Q3 + J3 overclaiming collide on the same sentences

J3 also covers overclaiming (“first/novel/state-of-the-art”, causal
language). Overclaiming is category 0 → class `correctness` in
`sweeps.md`, but Q7 of the writing rubric (“non-academic wording:
metaphor, hype, promotional adjectives”) will take the same sentence as
writing / ±1. Two honest judges, two scores, same pair.

---

## 4. Non-convergence of scores (by construction)

### D6.1 The loop does not test for improvement

```
nbt_pipeline.py:79-80
    The loop is FIXED-LENGTH: there is no convergence test, no "stop when
    unchanged", and no early exit on a round whose score did not improve.
```

Default `--stop-after-no-progress` is 0 (`nbt_pipeline.py:17598`,
`:14689`). A round that crowns A1 (“no demonstrable progress”,
`select_champion()` `:13178-13193`) still spends a full judge wave next
round.

### D6.2 Per-round statistics are defined as incomparable

`score_model_doc()` (`nbt_pipeline.py:15207-15210`):

> per-round champion statistics come from different panels and different
> fields and are NOT comparable across rounds; the vs_base margin of the
> final round is the only paired statement the decision supports.

So even if you log `median(champion)` vs round, the number is not a
learning curve. Causes:

- New judge identities / new salt / new label permutation every round.
- Field composition changes (round 1: 2 rewrites; round 2: 1 rewrite;
  original stays in every field).
- A new review of the new base, so the defect inventory is a different set.
- Ranking is median of a −4..+4 integer with 0 as the mode. Ties are the
  typical outcome; the mean of the same noisy list then IQR then
  **self-reported** `critical_remaining` / `writing_remaining` decide
  (`select_champion()` ranking key at `:13285-13328`;
  `score_model_doc()["tiebreaks"]` at `:15217`).

### D6.3 Tie-breaks are unverified for the arms that most often win ties

`candidate_tiebreak_inputs()` (`nbt_pipeline.py:13112-13139`):

> The frozen-review cross-check exists only for the arms that consume a
> `review/` directory (the revise arm) and only in the reported-zero
> direction; a rewrite or integration self-report is unverified.

An integrator that reports `writing_remaining: 0` beats an honest reviser
on a median tie. Rewrites are asked for `writing_remaining` of CATEGORY-2
issues they were **forbidden** to fix (claim-level defects go to
`PROBLEMS SURFACED`, `REWRITE_DIRECTIVES`:3575-3580). Honest high counts
lose ties.

### D6.4 `vs_base` is the only paired statistic and is unused

`aggregate_round()` records `vs_base` (`nbt_pipeline.py:12998-13002`)
and the decision report prints it, with the explicit note that it is
**not** a ranking input because `2*judges` directed scores are too few
for one outlier not to flip the sign. So the statistic that would
measure “did this round improve the incumbent?” is reported and unused.
The ranking key uses a *new* panel’s median instead.

---

## 5. Slow convergence, and merge-into-base is the wrong operator

### D5.1 Cost is in judging, not in repairing known defects

Default plan (`DEFAULTS` at `nbt_pipeline.py:757-765`):

```
rounds:      2
judges:      [3]
rewrites:    [2, 1]
revises:     [1, 1]
integrators: [0xFFFFFFFF]   # every pool member integrates
audit:       on             # DEFAULT_AUDIT
```

**Round 1** (~33 sessions): 2 rewrite + 1 review + 1 audit + 1 revise +
**4 integrate** + **24 judges** (8 field members × 3).

Pool = `{a1, w1, w2, a2}`. a1 is content-identical to `original`, so the
field is `{original, w1, w2, a2, i1, i2, i3, i4}` = **8** members.
Scores per version = `2 * 3 * 7 = 42`.

The module docstring (`nbt_pipeline.py:7-8`, `:150-154`) says “the
default plan’s round-1 field of 7 gives 36”. That under-counts `i1`.
The off-by-one is the same confusion as D4.1 (whether integrating into
the original produces a distinct member — it does, unless no ports
happen).

**Round 2** (~25 sessions): 1 rewrite + 1 review + 1 audit + 1 revise +
3 integrate + 18 judges. Field ≈ 7.

Call it **~58 Codex sessions, of which ~42 are judges**. Each judge
re-runs M1–M24 + J1–J4 on a whole corpus. The known finding list from
the review is **not** an input to the panel. You pay for rediscovery
instead of for applying the list you already have.

### D5.2 Rewrites are front-loaded and untargeted

Rewrites run **before** the review, from the base, with no findings
(`REWRITE_DIRECTIVES`:3417-3418, `:3447-3451`). They cannot aim at
`F-*`. The review is of `base/` only (`REVIEW_DIRECTIVES`:
`SUBMISSION_DIR = ./base`). Revise arms also start from `base/`, not
from a rewrite (`REVISE_DIRECTIVES`:2854-2856, `:2867-2869`).

So:

- Rewrite-only defects are never on the frozen list.
- The only consumer of the frozen list is the N=1 revise arm.
- Diversity is “organization you like”, not “different repairs of the
  known set”.
- Round 2 drops to M=1, and `rewrite_level_of(1, 1)` forces
  **structural** (`nbt_pipeline.py:1078-1087`). Sentence-level search
  is gone exactly when you wanted local polish.

The language pass in rewrite is also mis-scoped: it begins “After the
finding-led edits” (`LANGUAGE_PASS_RULE`:3658-3659), but rewrite has
no findings. L1–L3 (premise / logic slip / logic jump) contradict
rewrite hard rule 2 (“You may NOT change facts, numbers, citations,
claims”). The postcheck still requires all 11 coverage rows
(`check_language_pass()`, `:11598-11614`).

### D4.1 Integrating *into* every member, with the member frozen as base

```
nbt_pipeline.py:3231-3260  (INTEGRATE_DIRECTIVES)
=== THIS IS NOT A FREE-FOR-ALL MERGE — YOUR MEMBER STAYS THE BASE ===
  (c) the base fixed something the donor did not        -> KEEP AS-IS (base wins)
  (d) a defect present in the base AND in at least one donor
                                                        -> LEAVE UNTOUCHED
When several donors ... none is clearly better ... PREFER THE BASE's version
```

Default mask `0xFFFFFFFF` runs an integration for **every** pool
member, including a1 (the incumbent / original).

`i1 = A1 ← (W1, W2, A2)` is a full session whose starting point is the
*unrevised* manuscript. Class (d) then freezes every defect the original
shares with any donor — which is almost all of them. That arm is
expensive and biased toward the incumbent.

### D4.2 Shared defects are defined as not portable

Class (d) is how grammar, dashes, and terminology survive every round:

- Rewrite cannot change claims.
- Revise is the only arm that received the finding list, and there is
  only one of it.
- Integrate is forbidden from touching a defect that more than one
  package still has.
- Judges score the resulting near-copies as 0 on that defect
  (D3.2).

If the panel’s median is 0 (typical), ranking falls to self-reports and
digest; the incumbent base is the documented tie winner
(`select_champion()`: “an exact tie on median, mean and IQR keeps the
incumbent base”).

### D4.3 Integrators do not receive `review/`

`INTEGRATE_DIRECTIVES` carve-out (`nbt_pipeline.py:3323-3333`):

> There is NO review/ directory here … do NOT build an A1 ledger keyed
> to finding IDs … Do NOT run a pre-port review phase.

They port package *differences*, not findings. A2’s `F-*` repairs appear
only as diffs, competing with rewrite reorgs, under “prefer the base”.

`writing_remaining` / `critical_remaining` on the integrate marker are
self-reported with no frozen review to cross-check
(`INTEGRATE_DIRECTIVES`:3379-3385).

### D4.4 Regression scan only fails a *new family*

`scan_regression_problems()` (`nbt_pipeline.py:11617-11628`) fails a
stage that introduces a finding-tier family the input did not have at
all. Growth *inside* a family already present is a warning. A merge that
adds more nested parens to a document that already had one still ships.

W-07’s “counter-change artifact” was **not** implemented (residual
ledger §8: “partial … no dedicated counter-change artifact is
emitted”). A fix that creates a new sentence-level defect has no owner.

### D4.5 Language pass is a two-iteration local search, then stop

`LANGUAGE_PASS_RULE`: “iterate at most TWICE, then stop and report.”
Combined with “a step that introduces a finding-tier row is fixed
before the next step”, L9 (flow / em-dashes) and L11 (punctuation)
fight `FMT-T8b` / `FMT-T9c` inside those two iterations and then freeze.

### D4.6 Incumbent lock in selection

- Base is always eligible, including when it would fail the
  anti-regression gate (`select_champion()`:13195-13199: “the base is
  judged on its panel alone”).
- Fresh arms must beat the original *and* then beat the base on median.
- `vs_base` is not in the ranking key (D6.4).
- Exact statistical tie keeps the incumbent (`score_model_doc`
  `tiebreak_notes`, `:15219-15229`).

This is hill-climbing with a trust-region of radius 0 around A1. It
will not leave a local optimum except when the revise arm both
(i) actually repairs something the judges independently rediscover as
correctness/consistency and (ii) beats the incumbent on median — a high
bar for a ±1 writing signal.

---

## 6. Other mismatches that keep the loop off a single objective

### D8. One review, many unread packages

Judges, rewrites, and integrators never consume the frozen (audited)
list. The only stage aligned with the review is revise. Selection is by
a panel that is *required* not to know that list (blinding).

Blindness to *provenance* is right; blindness to the *defect inventory*
is not. Packages can stay anonymized while every judge still receives
the same id-stripped finding list.

### D9. Check-id contract drift across three documents

| Document | Required checks |
|----------|-----------------|
| Pipeline postcheck `check_review_contract` (`nbt_pipeline.py:10560-10566`) | M1–M17, M18, M19, M20, **M21–M24**, J1–J4 |
| `ADOPTED_SWEEPS_BLOCK` | same |
| `JUDGE_DIRECTIVES` frozen set | M1–M17, J1–J4 **ONLY**, plus M18–M20 spliced in |
| `SKILL.md` coverage / acceptance | M1–M20, J1–J4; “plus M21+ once proposals are adopted” |
| `sweeps.md` FINDING FORMAT (`:66`) | `check: <M1–M20\|J1–J4>` — **no M21–M24** |
| `PRIOR_ROUND_RULE` (`nbt_pipeline.py:10754-10755`) | “run the complete M1-M17 + J1-J4 set (plus the pipeline caption check)” |

Three documents, three checklists. A review that follows the skill is
incomplete under the postcheck; a judge that follows the directives
skips M21–M24 that the reviser had to satisfy.

### D10. Rewrite prompt packs Phase 1 + Phase 2 as “governing excerpts”

`rewrite_prompt()` (`nbt_pipeline.py:4513-4514`) appends
`ATTACHED_HEAD + ATTACHED_PHASE1 + ATTACHED_PHASE2`. Directives say this
is not a review; the attached master prompt says to run the complete
review including D0–D5. Integrate has an explicit carve-out
(`:3323-3336`); rewrite’s carve-out is only in the tail
(`REWRITE_TAIL`:3644-3647: “excerpts above are attached only for their
STYLE”). Agents follow the longest instruction.

### D11. Consistency test is a false green

`.nbt_test/test_agent_consistency_2026_0922.py`:

- `test_shared_blocks_everywhere` — shared block occurs once. Does not
  fail when role-private text contradicts it (D3.4, D2.3).
- `test_role_applicable_blocks` asserts
  `"Q1-Q11 correspond one-to-one to the"` — the Q12 / L1–L11 mismatch
  is *in that sentence*, so the test passes (D1.4).
- `test_check_id_coverage` contains
  `"M21" in nb.__dict__.get("__doc__", "") or True` (`:201-202`) — a
  tautology. The comment says “constant check below”; the real check
  is a source grep for a list-append, which does not prove the
  *prompts* require M21–M24 in the skill the agents actually read.

Private contradicting rules (`cosmetic wording = 0`, priority order
without `writing`, J3 optional, `FMT-T8b` vs M20, FINDING FORMAT
missing M21–M24) are untested.

### D12. Length caps still block wording fixes (W-08 not implemented)

Residual ledger P-18 / W-08: abstract pinned at 172/172, main text at
3,749/3,750. Caps are “never a gate” (`LENGTH_RULE`, C01/C02 of the
design-triage ledger) but they are a *de facto* block on splitting a
45-word abstract sentence. W-08 (“prefer ≤ cap−3 so the next
finding-driven edit has room”) is recorded as **not implemented**.

A reviser following E1’s M19 exception (`edit_rules.md`:14-24) may
cut redundancy to make room; a rewrite is told not to cut scientific
content to meet a cap (`M19_REWRITE_RULE`); a judge treats length as
advisory and never ranks on it. Three policies, one budget.

### D13. `SKILL.md` default `SUBMISSION_DIR = ./non-revised`

The review skill’s default path is `./non-revised`
(`nbt-skills/nbt-review/SKILL.md:10`). The pipeline overrides this to
`./base` in the orchestration directives and postchecks it
(`check_review_contract`, `nbt_pipeline.py:10533-10553`). The skill is
marked “governing prose” and is appended verbatim. An agent that
follows the skill’s Paths section rather than the override reviews the
pristine original in round 2+, while the postcheck demands `base/`.
That is a known class of contract-drift (design-triage C12 was the
fallback prompt; this is the live skill).

### D14. Header / plan arithmetic disagrees with the field it describes

`nbt_pipeline.py:7-8` and `:150-154` claim round 1 has 7 field members
and 36 directed scores. Under the default integrator mask the field is
8 members and 42 scores (D5.1). The plan comment at `:39-45` correctly
lists `I1 = A1 ← (W1..WM, A2..)` as a real arm. The scoring comment
silently drops it. Operators reading the header will provision the
wrong panel size.

---

## 7. Previously recorded items that are still open

From `NBT_RESIDUAL_ISSUE_LEDGER.md` §8 (implementation record,
2026-09-22), called out here only where the *design* residue remains:

| Workstream | Status then | Residue now |
|------------|-------------|-------------|
| W-07 fix-quality loop | partial | still no counter-change artifact (D4.4) |
| W-08 cap slack | not implemented | still blocks wording edits at the cap (D12) |
| W-10 auditor | implemented as a stage | stage exists; agenda still diverges from reviewer and judge (D2) |
| W-12 language pass + Q-rubric | implemented | L1–L11 vs Q1–Q12; Q1–Q3 parked on writing (D1.4) |
| W-11 arm levels | implemented | round 2 M=1 forces structural only (D5.2) |

The “one rule set” follow-up (`.nbt_test/test_agent_consistency_2026_0922.py`)
is the failed closure of this class: presence of a shared block is not
identity of the objective.

Items from `nbt_audit_data/PIPELINE_AUDIT_FINDINGS.md` (judge mtime
bias, label-map salt, retry context, visual gate, bookkeeping in the
judge corpus) are recorded as fixed and were not re-opened here.

---

## 8. What a coherent redesign would have to change

Not more prompts — **one objective, used everywhere**.

1. **One defect inventory per round**, id-stripped and handed to
   reviser, integrator, *and* judge. Judges stay blind to *who
   produced* a package; they should not be blind to *what was supposed
   to be fixed*. Score = how that inventory changed, computed in code
   from a rescan, not from a second LLM review.
2. **One dash/paren policy.** Either em-dashes are allowed as the
   nested-paren repair (and the density cap exempts those), or nested
   parens are repaired with commas only. Delete the other instruction.
3. **Move Q1–Q3 off the writing rubric** onto correctness (uncapped).
   Keep Q10–Q12 as writing, or drop the writing cap so grammar can
   actually decide a close pair. Add L12 if Q12 stays.
4. **Stop integrating into A1.** Default mask should skip bit 0 (the
   incumbent). Integrators should consume the audited finding list and
   be *forbidden* from class-(d) “leave shared defects”. Shared defects
   are the whole point of the revise arm; freezing them is how they
   survive every round.
5. **Review the candidate you are going to edit**, or revise the best
   rewrite, not always A1. Front-loading untargeted rewrites and then
   revising the original is two uncoordinated searches.
6. **Rank on a round-comparable statistic**: `vs_base` (or a frozen
   hidden test set), with the same judges reused or a code-side scan
   delta. Median of a new panel is not a loss function.
7. **Put a stopping rule on by default** (`--stop-after-no-progress 1`)
   and invert the session mix: 1 revise + 1 targeted rewrite *after*
   the review, 1 integrate, a small panel. Judging 8 near-copies with
   24 sessions is where the wall-clock goes.
8. **Make the consistency test fail on private contradictions**: no
   “cosmetic wording = 0” in the judge if the shared block says
   writing counts; `sweeps.md` class table must contain `writing`;
   FINDING FORMAT must list M21–M24; delete the `or True`.

Until those are the same function, more rounds will not help. The
machinery will keep producing a well-certified local edit of A1 whose
remaining grammar, dashes, and shared defects look identical to every
judge, score 0, and pin as champion.

---

## 9. Index of issues

| id | One-line |
|----|----------|
| D1.1 | `FMT-T8b` prescribes em-dash; `M20_REVISE_RULE` forbids it |
| D1.2 | `FMT-P1` advisory in the scanner, finding in `sweeps.md`; auditor only attacks finding-tier |
| D1.3 | L9 “make it flow” inserts dashes; rewrite M20 says don’t fix; judge Q11 ±1 |
| D1.4 | Writing rubric Q1–Q3 are correctness; Q12 has no L12 |
| D2.1 | Auditor drops are deleted from the reviser’s list |
| D2.2 | Judges re-derive a different list; frozen-set “ONLY” vs M21–M24 |
| D2.3 | `writing` class exists in `BASIS_TIERS` and nowhere in `sweeps.md` / judge priority order |
| D3.1 | Writing/formatting capped at ±1; cannot decide a comparison |
| D3.2 | Shared grammar is pairwise-invisible (score 0) |
| D3.3 | J3 “may be prioritized”; `unable` satisfies coverage |
| D3.4 | Judge private rule: wording preferences that don’t change meaning = 0 |
| D3.5 | Overclaiming is correctness in J3 and writing in Q7 |
| D4.1 | Default integrators include i1 = original ← others |
| D4.2 | Class (d) freezes shared defects |
| D4.3 | Integrators have no `review/` |
| D4.4 | Regression scan only fails a new rule family |
| D4.5 | Language pass stops after two iterations |
| D4.6 | Incumbent always eligible; exact tie keeps the base |
| D5.1 | ~42 of ~58 sessions are judges; known list is not an input |
| D5.2 | Rewrites run before review; round 2 M=1 is structural-only |
| D6.1 | Fixed-length loop; `--stop-after-no-progress` default 0 |
| D6.2 | Scores documented as incomparable across rounds |
| D6.3 | Tie-breaks self-reported and unverified off the revise arm |
| D6.4 | `vs_base` reported, not ranked on |
| D8 | Blindness to provenance extended (wrongly) to the defect inventory |
| D9 | M21–M24 required by pipeline, optional/absent in skill and FINDING FORMAT |
| D10 | Rewrite prompt appends full Phase 1+2 “governing” excerpts |
| D11 | Consistency test is presence-only, with an `or True` |
| D12 | Caps-at-the-ceiling still block wording edits (W-08 open) |
| D13 | Skill default `SUBMISSION_DIR=./non-revised` vs pipeline `./base` |
| D14 | Header says field of 7 / 36 scores; default plan is 8 / 42 |

---

## 10. Method

Read-only. Sources: `nbt_pipeline.py` (prompts, aggregation, selection,
score model), `nbt_docx_format.py` (scan tiers, em-dash, nested parens),
`nbt-skills/nbt-review/{SKILL.md,references/sweeps.md}`,
`nbt-skills/nbt-revise/references/edit_rules.md`,
`.nbt_test/test_agent_consistency_2026_0922.py`,
`NBT_RESIDUAL_ISSUE_LEDGER.md`, `NBT_DESIGN_TRIAGE_LEDGER.md`,
`nbt_audit_data/PIPELINE_AUDIT_FINDINGS.md`, `README.md`.

No agent session was re-run. Claims about session *counts* are from
`DEFAULTS` plus the round model in the module docstring; claims about
what an LLM *will* do with L9 are the documented instruction, not a
new measurement.

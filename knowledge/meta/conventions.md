---
type: Conventions
title: Knowledge bundle conventions
status: draft
---

# Conventions

Markdown with YAML frontmatter, one concept per file, file-relative links.
Checked by `scripts/okf-lint`.

## Directories and types

| Directory | `type` | Holds |
|---|---|---|
| `mechanics/` | `Mechanic` | How something in the game works: rules, rates, formulas, caps. |
| `data-locations/` | `DataLocation` | Where in the game files a setting lives, and how to change it (for mods). |
| `tools/` | `Tool` | Tools and data sources for analysing the game, with what they are good for. |
| `../research/questions/` | `Question` | Open questions; not part of the bundle, but the same frontmatter rules. |

## Concept frontmatter

```yaml
---
type: Mechanic                 # see above
title: Harvest All radius
status: draft                  # draft | stable | superseded
evidence_level: game-data      # game-data | code | measured | official |
                               # community-measured | community-claim | none
builds: ["25800958"]           # Steam build ids the evidence was observed on
stale_after: next-build        # next-build, or YYYY-MM-DD for dated sources
sources:                       # repo paths under research/sources/ or data/
  - research/sources/game-data/25800958/...
generated: {by: "machine:session", at: 2026-10-21}
verified: []                   # appended by reviewers
tags: [farming, freighter]
related: [../data-locations/harvest-all-radius.md]
verdict: >                     # optional; one paragraph a consumer can quote
  ...
---
```

Required: `type`, `title`, `status`, `evidence_level`, `stale_after`,
`sources`, `generated`, `verified`. `builds` is required unless
`evidence_level` is `community-claim`, `official` or `none`.

## Trust entries

`generated` and `verified` entries name a **role**, not a model:

| `by` | Meaning |
|---|---|
| `machine:session` | Written directly in a working session, not reviewed. |
| `machine:searcher` | Found by a research-run searcher. |
| `machine:reviewer` | Survived an adversarial review in a run (that run's id goes in `run`). |
| `human:bob` | Bob has read it and agrees. **Only Bob writes this.** |

A concept with only `machine:session` or `machine:searcher` entries is
unreviewed and says so by having `verified: []`.

## Body

1. **The answer** in one or two sentences, with the number if there is one.
2. **Evidence** — what each source shows, quoted where short; game-data
   values and their file and field.
3. **Scope and caveats** — build, mode, what is inferred rather than observed.
4. **Open** — what is still unknown, linking the question file.

## Sources

Every path in `sources` must exist. Game-data excerpts come from
`scripts/nms-pak cite`, web pages from `scripts/research-fetch`, measurements
are hand-written files in `research/sources/measurements/` stating method,
readings, build and date. `data/nms_tables.json#<section>` is an acceptable
source for values the extractor pulled from the paks (its `meta` gives the build).

## Staleness

`stale_after: next-build` concepts whose `builds` do not include the installed
build are flagged by the lint for re-checking, not deleted. Re-checked
concepts append the new build.

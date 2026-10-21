export const meta = {
  name: 'nms-deep-research-run',
  description: 'nms-exporter mechanics research run (parameterised by args): fable plan, opus managers, sonnet searchers, cross-assigned opus review, fable synthesis',
  phases: [
    { title: 'Plan', detail: 'fable decomposes the brief into sub-questions and search angles' },
    { title: 'Investigate', detail: 'opus manager per sub-question, sonnet searchers per angle, sources stored as they are read' },
    { title: 'Consolidate', detail: 'opus manager second pass: easy agreement, and what nobody looked for' },
    { title: 'Review', detail: 'fresh opus reviewer per sub-question, briefed to refute; assigns evidence levels' },
    { title: 'Synthesise', detail: 'fable writes synthesis.md and the concept drafts' },
  ],
}

const RUN = args.run
const DATE = args.date
const BUILD = args.build

const HOUSE = `
## House rules — binding on every agent in this run

Working directory is the repo root (/home/bob/Projects/nms-exporter). Run directory: \`${RUN}\`.
Today is ${DATE}. The installed game build is **${BUILD}** (Steam build id). The brief is
\`${RUN}/brief.md\` and is authoritative. The charter is \`research/index.md\`.

**Privacy:** never put Bob's player name, base names, ship names or galactic addresses into a web
query or a stored source. Describe situations generically.

**Storage — not optional, not a cleanup step. If a claim cites it, it is stored:**
- Game files: \`scripts/nms-pak find '<regex>'\` to locate, \`scripts/nms-pak get '<regex>'\` to unpack
  and convert, \`scripts/nms-pak grep '<pattern>' --in '<path regex>'\` to search what is unpacked,
  \`scripts/nms-pak cite <path> --lines A-B --why '<why>'\` to store the excerpt a claim rests on.
  \`scripts/nms-data item|recipes|uses|search|crops|biomes\` queries the already-extracted tables;
  \`data/nms_tables.json#<section>\` is a valid source for those values.
- Web pages: \`scripts/research-fetch <url> --slug <slug> --why '<why>'\`. For MediaWiki pages fetch the
  raw article (\`?action=raw\`). It never overwrites; pick a new slug.
- Notes you derive, censuses and anything else: \`${RUN}/raw/\`.
- Every \`sources[]\` entry you return must be a path that exists under \`research/sources/\`,
  \`data/\` or \`${RUN}/raw/\`.

**Absence claims** ("not in the game files", "nobody has measured X") need the search that would have
found it to have been *run*: the \`nms-pak find\` / \`grep\` commands or web queries in
\`commands_run\`, output stored as \`${RUN}/raw/census-<sqid>-<angle>-<slug>.md\`. Otherwise the wording
is "not found in what we searched", and "hardcoded" is a hypothesis, never a finding.

**Scope:** every finding names the build(s) it was observed on (\`builds\`), or for community material
the patch/date it was written against. A source with neither is flagged \`builds: unknown\`.

**Tools:** if \`WebSearch\` / \`WebFetch\` are not loaded, load them with \`ToolSearch\` query
\`select:WebSearch,WebFetch\`. Use Bash for the repo tools. Never write to \`knowledge/\` — this workflow
produces proposals only. Never run the game, edit saves, or touch the live exporter service.

${args.house_extra}
`

const PLAN_SCHEMA = {
  type: 'object',
  required: ['subquestions'],
  properties: {
    subquestions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'title', 'question', 'scope_rule', 'answer_criteria', 'falsifier', 'angles'],
        properties: {
          id: { type: 'string', description: 'sq1..sqN' },
          title: { type: 'string' },
          question: { type: 'string' },
          scope_rule: { type: 'string', description: 'which builds, modes and platform an answer must hold for' },
          answer_criteria: { type: 'string' },
          falsifier: { type: 'string' },
          angles: {
            type: 'array',
            items: {
              type: 'object',
              required: ['id', 'kind', 'brief', 'seed_queries'],
              properties: {
                id: { type: 'string' },
                kind: { type: 'string', description: 'game-data | code | save-measurement | official | community-measured | community-claim | mod-sources' },
                brief: { type: 'string' },
                seed_queries: { type: 'array', items: { type: 'string' } },
              },
            },
          },
        },
      },
    },
  },
}

const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['findings', 'commands_run', 'raw_files', 'absence_claims', 'what_i_could_not_get'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['claim', 'kind', 'builds', 'sources', 'read_depth', 'quote', 'value_or_behaviour'],
        properties: {
          claim: { type: 'string' },
          kind: { type: 'string', enum: ['game-data', 'code', 'measured', 'official', 'community-measured', 'community-claim'] },
          builds: { type: 'string', description: 'build ids, or the patch/date a community source was written against, or "unknown"' },
          value_or_behaviour: { type: 'string', enum: ['value', 'behaviour'], description: 'a number/field in the data, or how the game acts' },
          sources: { type: 'array', items: { type: 'string' } },
          read_depth: { type: 'string', enum: ['full', 'partial', 'snippet-only'] },
          contradicts: { type: 'string' },
          quote: { type: 'string', description: 'the line or sentence the claim rests on, verbatim' },
          confidence_note: { type: 'string' },
        },
      },
    },
    commands_run: { type: 'array', items: { type: 'string' } },
    raw_files: { type: 'array', items: { type: 'string' } },
    absence_claims: {
      type: 'array',
      items: {
        type: 'object',
        required: ['claim', 'searches_executed', 'census_stored_at'],
        properties: {
          claim: { type: 'string' },
          searches_executed: { type: 'array', items: { type: 'string' } },
          census_stored_at: { type: 'string' },
          strength: { type: 'string', enum: ['established-absent', 'not-found-in-what-we-searched'] },
        },
      },
    },
    what_i_could_not_get: { type: 'string' },
  },
}

const MANAGER_SCHEMA = {
  type: 'object',
  required: ['searchers'],
  properties: {
    searchers: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'kind', 'brief', 'seed_queries'],
        properties: {
          id: { type: 'string' },
          kind: { type: 'string' },
          brief: { type: 'string' },
          seed_queries: { type: 'array', items: { type: 'string' } },
        },
      },
    },
    notes: { type: 'string' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['items', 'headline_evidence_level', 'evidence_level_note', 'what_nobody_looked_for', 'verdict'],
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        required: ['claim', 'verdict', 'reason'],
        properties: {
          claim: { type: 'string' },
          verdict: { type: 'string', enum: ['survived', 'weakened', 'killed'] },
          evidence_level: { type: 'string', enum: ['game-data', 'code', 'measured', 'official', 'community-measured', 'community-claim', 'none'] },
          scope_verdict: { type: 'string', description: 'does it hold for the installed build and the default mode?' },
          reason: { type: 'string' },
          spot_check: { type: 'string' },
        },
      },
    },
    headline_evidence_level: { type: 'string' },
    evidence_level_note: { type: 'string' },
    what_nobody_looked_for: { type: 'string' },
    verdict: { type: 'string' },
  },
}

// ---------------------------------------------------------------- Plan
phase('Plan')

const plan = await agent(`You are the planning tier of a mechanics research run in the nms-exporter repo.

${HOUSE}

Read first: \`${RUN}/brief.md\` (authoritative; do not re-scope it), \`.claude/skills/deep-research/SKILL.md\`,
\`research/index.md\`, \`knowledge/meta/conventions.md\`, and the question files and concepts the brief names.

Produce the decomposition for the sub-questions the brief fixes (do not invent or merge). For each:
the precise question, the scope rule, what counts as an answer, what would falsify it, and search
angles that differ in **kind**: game-data (pak files), code (runtime hooks, decompilation notes),
save-measurement (what consecutive saves would show, and what Bob would have to do in game),
official (patch notes), community-measured, community-claim, mod-sources (what mods change and in
which files). Reworded synonyms are not a second angle. Keep "value in the data" and "behaviour in
game" as separate answer criteria where both apply.

${args.plan_extra}

For each sub-question name the \`nms-pak find\`/\`grep\` census that must be run and stored before
anything is called absent from the game files.

Write the readable plan to \`${RUN}/plan.md\`, then return the structured decomposition.`,
  { model: 'fable', label: 'plan', phase: 'Plan', schema: PLAN_SCHEMA })

log(`Plan: ${plan.subquestions.length} sub-questions, ${plan.subquestions.reduce((n, s) => n + s.angles.length, 0)} angles`)
const ids = plan.subquestions.map((s) => s.id)

// ---------------------------------------------------------------- Investigate → Consolidate → Review
const results = await pipeline(
  plan.subquestions,

  async (sq) => {
    const m = await agent(`You are the opus manager for **${sq.id} — ${sq.title}**.

${HOUSE}

**You do not search.** You brief searchers; you read repo files only.

Sub-question: ${sq.question}
Scope rule: ${sq.scope_rule}
What counts as an answer: ${sq.answer_criteria}
What would falsify it: ${sq.falsifier}

Proposed angles:
${JSON.stringify(sq.angles, null, 2)}

Read \`${RUN}/brief.md\` and \`${RUN}/plan.md\`. Turn each angle into a working brief for one sonnet
searcher: what to find, what would falsify it, seed queries or \`nms-pak\` regexes, which sites, and
what NOT to spend tokens on. One searcher per angle.

Write your briefing pack to \`${RUN}/raw/${sq.id}-manager.md\` and return the structured briefs.`,
      { model: 'opus', label: `manage:${sq.id}`, phase: 'Investigate', schema: MANAGER_SCHEMA })
    return { sq, searchers: m.searchers }
  },

  async (prev) => {
    const { sq, searchers } = prev
    const returns = await parallel(searchers.map((s) => () =>
      agent(`You are a sonnet searcher on **${sq.id} — ${sq.title}**, angle **${s.id} (${s.kind})**.

${HOUSE}

Sub-question: ${sq.question}
Scope rule: ${sq.scope_rule}

**Your brief:**
${s.brief}

Seed queries / regexes (a starting point, not a limit):
${s.seed_queries.map((q) => '- ' + q).join('\n')}

Search, retrieve, **store what you read**, and read what you stored. Return structured findings, never
prose. Every finding carries the verbatim \`quote\` (or the XML line) it rests on, its \`builds\`, and
whether it is a value in the data or a behaviour in game.

If the angle turns up nothing, try other vocabulary (internal ids, Gc* class names, UI_ string keys via
\`scripts/nms-data strings\`) first; then record an executed absence with its census stored under
\`${RUN}/raw/census-${sq.id}-${s.id}-<slug>.md\`.

Also write a readable summary to \`${RUN}/raw/${sq.id}-${s.id}-findings.md\`.`,
        { model: 'sonnet', label: `search:${sq.id}-${s.id}`, phase: 'Investigate', schema: FINDINGS_SCHEMA })
    ))
    return { ...prev, returns: returns.filter(Boolean) }
  },

  async (prev) => {
    const { sq, returns } = prev
    const consolidated = await agent(`You are the opus manager for **${sq.id} — ${sq.title}**, second pass.

${HOUSE}

Your searchers returned:

${JSON.stringify(returns, null, 2)}

Not a summary. Answer:
1. **What did they agree on too easily?** Several wiki pages, mod pages and videos repeating one
   original claim are one source. Name every case.
2. **What did nobody look for?** Concretely: a file, a Gc* struct, a measurement, a patch note.
3. **Which claims are load-bearing** for the brief's decision, which are texture.
4. **Scope audit** — any claim from an older patch or another mode doing work for the current build.
5. Verify with \`ls\` that every cited source path exists. Report any that do not. Fetch nothing new.

Write it to \`${RUN}/raw/${sq.id}-consolidated.md\` and the raw returns verbatim to
\`${RUN}/raw/${sq.id}-searcher-returns.json\`. Return the consolidation as prose.`,
      { model: 'opus', label: `consolidate:${sq.id}`, phase: 'Consolidate' })
    return { ...prev, consolidated }
  },

  async (prev, _orig, idx) => {
    const { sq, returns, consolidated } = prev
    const managedBy = ids[(idx + 1) % ids.length]
    const review = await agent(`You are the adversarial reviewer (opus) for **${sq.id} — ${sq.title}**. (Cross-assignment: you are the tier that managed ${managedBy}, never ${sq.id}.)

${HOUSE}

**You did not find any of this. Your brief is to refute. Default to "not established".** You alone
assign \`evidence_level\`.

Sub-question: ${sq.question}
What would have falsified it: ${sq.falsifier}

Searcher returns:
${JSON.stringify(returns, null, 2)}

Manager's consolidation:
${consolidated}

**Spot-check raw material yourself**: open at least four cited sources (game-data excerpts, stored
pages) and check the value or sentence is really there. For game-data claims, re-run the
\`scripts/nms-pak grep\` yourself. Record what you opened in \`spot_check\`.

Lenses:
- **Version laundering** — community material from an earlier patch cited as current; a game-data
  excerpt from another build.
- **Data is not behaviour** — a field's value cited as proof of what the game does. Grade the value
  \`game-data\` and the behaviour only by code or measurement.
- **Mode and platform** — difficulty presets, custom settings, expeditions, console builds.
- **Mod pages as evidence** — an author's description of intent, for the version they built against.
- **One source read as many**; **read_depth**; **staleness**.
- **Absence** — check the search is in \`commands_run\` and the census stored; run
  \`grep -ril '<term>' research/sources knowledge\` yourself with two or three synonyms and record it.
${args.review_extra || ''}

Write the full review to \`${RUN}/raw/review-${sq.id}.md\`: challenged, survived, killed, with killed
findings kept and their refutations recorded. Then return the structured review.`,
      { model: 'opus', effort: 'high', label: `review:${sq.id}`, phase: 'Review', schema: REVIEW_SCHEMA })
    return { sq: { id: sq.id, title: sq.title, question: sq.question }, review, consolidated }
  }
)

const done = results.filter(Boolean)
log(`Reviews complete for ${done.length}/${plan.subquestions.length} sub-questions`)

// ---------------------------------------------------------------- Synthesise
phase('Synthesise')

const synthesis = await agent(`You are the synthesising tier of this nms-exporter research run.

${HOUSE}

All sub-questions have been searched, consolidated and reviewed:

${JSON.stringify(done, null, 2)}

Read \`${RUN}/brief.md\`, then every \`${RUN}/raw/review-sq*.md\` in full. Read the concepts the brief
names: say which this run **extends**, **revises**, or leaves untouched.

Write \`${RUN}/synthesis.md\`:
- **The answer at the top**, per decision the brief names (exporter, planner, play, mod), or a plain
  statement that it is not decidable from what was found.
- Values and behaviours kept apart; contradictions named, not averaged; reviewer riders unaltered.
- What a measurement by Bob would settle, as concrete in-game steps and which save fields to read.
- Open questions as proposed question files (frontmatter per \`research/questions/*.md\`) in
  \`${RUN}/raw/proposed-questions.md\`.

${args.synth_extra}

Then write the proposed concept files **in full** per \`knowledge/meta/conventions.md\` to
\`${RUN}/raw/concept-drafts.md\`: \`evidence_level\` exactly as the reviewer assigned, \`builds\`,
\`stale_after\`, \`sources\`, \`generated: {by: "machine:searcher", at: ${DATE}}\`,
\`verified: [{by: "machine:reviewer", at: ${DATE}, run: "${RUN}"}]\`, \`status: draft\`, and a \`verdict:\`
on any concept the exporter or planner would rely on. **Never write \`human:bob\`.**

Do not write to \`knowledge/\`. Return a short plain-text summary of the verdicts and what you propose
to promote.`, { model: 'fable', effort: 'high', label: 'synthesise', phase: 'Synthesise' })

return {
  subquestions: done.map((d) => ({ id: d.sq.id, title: d.sq.title, headline: d.review.headline_evidence_level, verdict: d.review.verdict })),
  synthesis,
}

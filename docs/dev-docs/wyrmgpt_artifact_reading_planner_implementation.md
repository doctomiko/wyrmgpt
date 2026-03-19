# WyrmGPT Implementation Plan — Capacity-Aware Artifact Reading Planner and Self-Healing Artifact Maps

## Purpose

This document translates the design into an implementation sequence that survives chat/session loss and can be executed incrementally.

The goal is to add:
- capacity-aware whole-artifact planning
- self-healing artifact summary/index metadata
- staged reading behavior
- transparent planner events
- later continuation across rounds

---

## Guiding Principle

Do not try to ship the final cathedral in one pass.

Build this in layers:
1. capacity estimation
2. summary/index readiness
3. summary/index generation
4. planner decision object
5. planner event persistence and UI
6. staged reading continuation

---

## Current System Assumptions

The codebase already has:
- artifacts
- corpus_chunks
- chunking
- embeddings
- retrieval
- citations
- retained artifacts
- web sources and snapshots
- URL ingestion path
- conversation context/debug surfaces

This plan reuses those instead of replacing them.

---

## Stage 1 — Capacity Estimation

### Goal
Know when whole-artifact expansion is likely unsafe before trying it.

### Required Work

#### 1.1 Deployment configuration
Make sure each deployment can expose or derive:
- max context tokens
- recommended response budget
- optional safe expansion budget

If deployment config does not already include a max-context field, add it.

#### 1.2 Artifact token estimates
Add or compute:
- artifact estimated token count
- chunk count

This can be:
- precomputed and stored in artifact metadata, or
- estimated on demand from chunk counts and text length

#### 1.3 Whole-expansion budget helper
Add a helper, likely in `server/context.py` or a new planner module:

`estimate_whole_artifact_fit(...)`

Inputs:
- deployment
- current conversation prompt size
- candidate artifact ids

Output:
- projected load
- fit classification
- per-artifact estimates

### Deliverable
A function that can answer:
"Can these artifacts safely be whole-included this turn?"

---

## Stage 2 — Artifact Summary and Index Metadata Readiness

### Goal
Before whole expansion or staged reading, ensure the artifact has the maps needed.

### Required Work

#### 2.1 Artifact metadata shape
Choose where to store:
- summary_text
- summary_updated_at
- summary_model
- index_json
- index_updated_at
- index_model
- artifact_text_hash

Recommended storage:
- sidecar artifact metadata JSON or dedicated metadata fields/table

Do not attach this to the artifact content hash used for rechunk triggers.

#### 2.2 Freshness check helper
Add a helper, likely in `server/db.py` or `server/artifactor.py`:

`artifact_maps_status(artifact_id)`

Returns whether:
- summary exists
- index exists
- summary is stale
- index is stale

#### 2.3 Self-healing hook
On artifact create / update / retrieval, check readiness and decide whether to regenerate maps.

### Deliverable
A reliable way to ask:
"Does this artifact already have a usable summary and index?"

---

## Stage 3 — Hierarchical Summary Generation

### Goal
Summarize large artifacts without requiring whole inclusion into the summary model.

### Required Work

#### 3.1 Chunk summary routine
Add a function, probably in `server/summary_helper.py` or a new artifact-summary module:

`generate_chunk_summaries_for_artifact(artifact_id, summary_deployment)`

Behavior:
- load ordered chunks
- summarize each chunk with the summary model
- store the summaries in order

#### 3.2 Artifact summary synthesis
Add:

`generate_artifact_summary_from_chunk_summaries(...)`

Behavior:
- input: ordered chunk summaries
- output: artifact-level summary

#### 3.3 Index generation
Add:

`generate_artifact_index(...)`

Behavior:
- first, use author-provided headings if available from chunking metadata
- otherwise, infer scenes/sections from ordered chunk summaries

Each index entry should include:
- label
- summary
- chunk_start
- chunk_end

### Deliverable
A self-healing pipeline that can create summary + index for large artifacts on demand.

---

## Stage 4 — Planner Decision Object

### Goal
When whole inclusion is too large, create a real plan rather than silently failing or truncating.

### Required Work

#### 4.1 New planner module
Create something like:
`server/artifact_reading_planner.py`

#### 4.2 Planner input
Inputs should include:
- latest user message
- candidate artifact ids
- artifact map readiness
- capacity estimate
- conversation retained artifacts
- reading intent classification

#### 4.3 Planner output schema
Use a structured object, for example:

```json
{
  "mode": "reading",
  "primary_artifact_ids": [],
  "deferred_artifact_ids": [],
  "strategy": [],
  "reason": "",
  "next_action": {}
}
```

Do not reduce this to a single letter option.

#### 4.4 Strategy combinations
Support composable strategies such as:
- use_summary
- use_index
- focus_primary
- defer_secondary
- sequential_read
- selective_reference_rag

### Deliverable
A planner object that can be parsed and acted on by scaffolding.

---

## Stage 5 — Planner Event Persistence

### Goal
Make planner behavior visible and durable.

### Required Work

#### 5.1 New persistence table(s)
Recommended additions:
- `artifact_planner_events`
or a more general scaffold-event table if you prefer a broader future path.

Suggested fields:
- id
- conversation_id
- message_id
- event_kind
- planner_input_json
- planner_output_json
- status
- created_at
- updated_at

#### 5.2 Event creation
When the planner triggers, create a row immediately.

#### 5.3 Conversation thread surfacing
Return planner event payload in conversation context so UI can render it inline.

### Deliverable
Planner decisions become inspectable artifacts of the conversation rather than hidden logic.

---

## Stage 6 — Context Assembly Changes

### Goal
Use planner results to decide what enters the model context.

### Required Work

#### 6.1 Whole-expansion gate
Before whole artifact inclusion, run capacity estimation.

If overload likely:
- do not whole-include by default
- switch to planner path

#### 6.2 Summary/index fallback
When whole inclusion is denied:
- include summary
- include index
- include selected sections/chunks if appropriate

#### 6.3 Reading-mode behavior
If reading mode and too large:
- include summary + index + first staged read window
- retain progress

#### 6.4 Reference-mode behavior
If lookup/reference mode and too large:
- include summary + index + top relevant chunk windows
- do not pretend to have read the whole thing

### Deliverable
Context assembly becomes capacity-aware and mode-aware.

---

## Stage 7 — Reading Session Persistence

### Goal
Support continuing through large works over multiple rounds.

### Required Work

#### 7.1 Session table(s)
Add either:
- lightweight fields to retained artifacts, or
- dedicated tables

Recommended dedicated tables:
- `artifact_reading_sessions`
- `artifact_reading_steps`

#### 7.2 Session state
Track:
- current artifact
- current section/chunk range
- completed sections
- deferred sections
- summary-so-far
- status

#### 7.3 Continuation helper
Add a helper:
`get_next_reading_step(conversation_id, artifact_id)`

### Deliverable
The system can come back later to unread sections instead of starting over.

---

## Stage 8 — UI Work

### Goal
Make the planner and staged reading visible to the user.

### Required Work

#### 8.1 Planner card in thread
Render scaffold planner events as a collapsible card.

Show:
- artifact titles
- fit estimate / overload reason
- selected strategy
- deferred items
- next step

#### 8.2 Artifact reading status
In conversation and project views, show:
- summary available
- index available
- staged reading in progress
- last section read

#### 8.3 Manual controls
Later add:
- refresh summary
- refresh index
- mark artifact as "read for enjoyment"
- resume reading
- focus this artifact now

### Deliverable
Users can see what is taking time and why.

---

## Stage 9 — Self-Healing Rules

### Goal
Keep summary/index metadata fresh without creating loops.

### Required Work

#### 9.1 Hash boundary
Ensure artifact text hash ignores:
- summary_text
- index_json
- summary timestamps
- index timestamps

#### 9.2 Refresh triggers
Refresh summary/index when:
- artifact content changed
- summary/index missing
- summary/index marked stale
- user explicitly requests refresh

#### 9.3 No circular re-chunking
Writing summary/index metadata must not trigger:
- rechunk
- rehash as content change
- infinite refresh loops

### Deliverable
Stable metadata lifecycle.

---

## Proposed File / Module Changes

### Likely touched modules
- `server/context.py`
- `server/db.py`
- `server/artifactor.py`
- `server/summary_helper.py`
- `server/query_retrieval.py`
- `server/main.py`
- `server/static/app.js`
- `server/static/index.html`

### Likely new modules
- `server/artifact_reading_planner.py`
- `server/artifact_summary_maps.py` (optional; could also live inside summary_helper)

---

## Suggested Commit Sequence

### Commit 1 — capacity plumbing
- add deployment max-context awareness
- add artifact token/chunk estimation helper
- add fit-estimation helper

### Commit 2 — summary/index metadata plumbing
- add metadata fields or sidecar storage
- add freshness check helper

### Commit 3 — chunk-summary pipeline
- generate chunk summaries
- generate artifact summary from chunk summaries

### Commit 4 — index generation
- headings-first index
- scene inference fallback
- persist `chunk_start` / `chunk_end`

### Commit 5 — planner object and decision logic
- add planner module
- emit structured plan JSON

### Commit 6 — planner persistence
- store planner events
- expose planner events to UI payloads

### Commit 7 — context assembly integration
- whole-expansion gate
- summary/index fallback
- staged reading inclusion

### Commit 8 — reading sessions
- persist progress
- resume later

### Commit 9 — UI surfacing
- planner cards
- reading progress display
- refresh actions

---

## Minimal First Vertical Slice

If you want the fastest meaningful version, build just this:

1. estimate fit
2. if too large, ensure summary/index exist
3. include summary/index instead of full artifact
4. emit a planner event explaining what happened

That alone gives you:
- overload protection
- transparency
- self-healing artifact maps
- a base for later staged reading

---

## Testing Plan

### Unit tests
- fit estimation
- chunk-summary generation
- index generation from headings
- scene inference fallback
- hash stability rules

### Integration tests
- large artifact whole-read request triggers planner
- summary/index generated on demand
- summary/index metadata writes do not re-chunk artifact
- planner event appears in conversation payload

### UX tests
- planner card visible
- deferred artifacts visible
- continuation possible on later turn

---

## Future Extensions

- richer scene inference
- confidence scoring on inferred sections
- multiple planner strategies by deployment/provider
- cross-artifact synthesis plans
- selective mood/tone reading for literary analysis
- patent-specific prior-art claim support materials

---

## "Done" Definition

This subsystem is meaningfully implemented when:
- oversized whole-artifact requests trigger fit estimation
- summary/index are created or refreshed automatically when needed
- the system can include summary/index instead of full expansion
- planner decisions are visible in the conversation
- metadata updates do not retrigger chunking
- later phases can add staged reading without redesign

---

## Closing

This plan turns oversized-artifact handling into an explicit, inspectable scaffold process.

Instead of either:
- pretending the model read the whole work, or
- giving up and doing search-only chunk retrieval,

the system becomes capable of planning, mapping, and continuing through large artifacts in a controlled way.

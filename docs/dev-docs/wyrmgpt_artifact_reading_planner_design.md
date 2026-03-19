# WyrmGPT Design Doc — Capacity-Aware Artifact Reading Planner and Self-Healing Artifact Maps

## Purpose

This document captures the design of a system for handling **whole-artifact reading requests** when the artifact may be too large to fit into a model context window.

It is written to support:
- engineering implementation
- architectural handoff across chat sessions
- potential IP / patent counsel review
- future extension to web pages, PDFs, prose, fiction, poetry, transcripts, technical references, and mixed document sets

This document is not legal advice. It is a technical description of the process as currently conceived.

---

## Problem Statement

Conventional retrieval-augmented systems are built primarily for **lookup mode**:

- "What does this document say about X?"
- "Find the relevant chunk."
- "Answer my question using the top passages."

That is not enough for another valid user intent:

- "Read this story for enjoyment and tell me what you think."
- "Take in this essay as a whole."
- "Read this long article and respond as a reader, not as a search engine."

For many works, a handful of topical chunks is not a meaningful substitute for reading the whole work. This is especially true for:
- short stories
- novels
- poems
- narrative nonfiction
- rhetorical essays
- longform prose without headings
- scene-driven works
- documents whose meaning depends on sequence and accumulation

At the same time, contexts are finite. A system cannot responsibly whole-expand arbitrarily large artifacts every time a user asks.

This design introduces a new subsystem: **Artifact Reading Planner**.

The Artifact Reading Planner is a capacity-aware, intent-aware scaffold layer that decides how a large artifact should be processed when the user requests **whole-artifact reading** or when retrieval attempts to fully expand an artifact but the payload is likely too large.

It complements ordinary RAG rather than replacing it.

---

## Core Thesis

The system should distinguish between:

1. **Lookup / reference mode**
2. **Reading / enjoyment / whole-work mode**

Both modes require capacity planning, but they lead to different expansion strategies.

If a whole artifact is too large, the system should not merely fail or silently truncate. It should produce a **reading plan** that allows the system to:
- preserve continuity
- keep the user informed
- create or refresh summaries and indexes as needed
- read in parts when necessary
- remember progress across rounds
- return to unread sections later

---

## Terminology

### Artifact
The readable content object already used by WyrmGPT after files, web pages, transcripts, or other source materials are normalized into text.

### Chunk
A retrieval unit produced from artifact text.

### Artifact Summary
A compact, ordered description of the artifact as a whole, generated from chunk-level summaries if needed.

### Artifact Index
A structured map of sections or scenes within an artifact. Each entry includes at minimum:
- title / label
- summary
- `chunk_start`
- `chunk_end`

### Reading Plan
A scaffold-generated plan for how to process one or more artifacts when whole inclusion is too large.

### Reading Session
Conversation-scoped persistent state that tracks how an artifact is being consumed across rounds.

### Retained Artifact
An artifact previously pulled into a conversation and remembered for future rounds.

### Planner Event
A visible scaffold step recorded in the conversation explaining the strategy chosen for oversized artifacts.

---

## Design Goals

1. Prevent context overload.
2. Preserve coherent reading behavior for long works.
3. Support both lookup and whole-reading intent.
4. Reuse the existing artifact -> chunk -> embedding pipeline.
5. Avoid circular updates when summary/index metadata changes.
6. Self-heal summaries and indexes on demand.
7. Preserve transparency to the user.
8. Allow staged reading across multiple rounds.
9. Support multiple artifact types using one framework.
10. Make future UI features possible without redesign.

---

## High-Level System Overview

When the user or retrieval path triggers whole-artifact inclusion, the system performs these steps:

1. **Intent detection**
2. **Capacity planning**
3. **Artifact metadata readiness check**
4. **Planner decision**
5. **Plan persistence**
6. **Execution**
7. **Conversation memory / continuation**

### Step 1 — Intent Detection

The scaffold first classifies whether the user's request appears to be:
- lookup mode
- reading mode
- mixed mode

Examples of reading-mode cues:
- "read this"
- "take it in"
- "tell me your thoughts"
- "respond as a reader"
- "for enjoyment"
- "what did you think of the work"

Examples of lookup-mode cues:
- "what does it say about"
- "find the part where"
- "explain the section on"
- "summarize the technical argument"

### Step 2 — Capacity Planning

The scaffold estimates whether full inclusion is likely to fit.

Inputs include:
- deployment context limit
- current conversation context usage
- system prompt budget
- artifact count
- artifact token estimates
- chunk count
- retained artifacts already in scope

The result is a binary-ish answer plus a margin estimate:
- fits comfortably
- probably fits
- borderline
- likely too large
- definitely too large

Capacity planning is used in **all modes**, not just reading mode.

### Step 3 — Artifact Metadata Readiness Check

For each artifact considered for whole inclusion, the system checks whether the artifact has:
- summary
- index / table of contents / scene map
- chunk count
- estimated token count
- freshness markers for summary/index metadata

If summary or index is missing or stale, the system should generate or refresh it as needed.

### Step 4 — Planner Decision

If the combined artifact load is too large, the planner chooses a strategy.

The planner should output a structured plan, not just a single letter option.

Example:

```json
{
  "mode": "reading",
  "primary_artifact_ids": ["artifact-1"],
  "deferred_artifact_ids": ["artifact-2", "artifact-3"],
  "strategy": [
    "use_existing_summary",
    "use_existing_index",
    "focus_primary_artifact",
    "sequential_read"
  ],
  "reason": "Artifact 1 exceeds safe whole-context size; user intent indicates holistic reading rather than lookup.",
  "next_action": {
    "type": "read_sections",
    "artifact_id": "artifact-1",
    "section_range": [0, 2]
  }
}
```

### Step 5 — Plan Persistence

The planner result is stored as a **visible scaffold event** in the conversation, not hidden.

The system should preserve:
- the planner prompt inputs
- the planner output plan
- the selected artifacts
- the reason for deferral or focus
- the execution status

### Step 6 — Execution

Depending on the plan, execution may include:
- full artifact include
- summary-only include
- index-only include
- selected section/chunk range include
- staged sequential read
- focus on one artifact and defer others
- hybrid combinations

### Step 7 — Conversation Memory / Continuation

The system remembers:
- which artifacts were introduced
- which artifacts were read in full
- which sections/chunk ranges were already consumed
- which sections remain
- carry-forward summary or interpretation notes

This enables follow-up rounds without starting over.

---

## Reading Modes

### Mode A — Ordinary Lookup / Reference
Used when the user wants specific facts or relevant passages.

Behavior:
- use standard chunk retrieval
- include relevant chunk windows
- include summary/index if whole artifact is too large
- avoid full expansion unless the artifact safely fits

### Mode B — Whole-Artifact Reading
Used when the user wants a holistic response.

Behavior:
- try full inclusion if it safely fits
- otherwise generate or reuse summary + index
- read in sequence over multiple rounds if needed
- preserve progression
- return interpretive thoughts as a reader

### Mode C — Mixed Mode
Used when the user wants both a holistic reaction and also answers to particular questions.

Behavior:
- summary + index for global frame
- selected sections/chunks for local detail
- staged continuation if needed

---

## Capacity Planning Heuristics

A simple first-pass heuristic is acceptable and useful.

Inputs:
- deployment maximum context tokens
- estimated current prompt load
- estimated artifact token count
- artifact chunk count
- number of artifacts requested for full inclusion

### Heuristic Strategy
1. Compute estimated available budget for whole artifacts.
2. Estimate artifact load from chunk counts / token estimates.
3. If total projected artifact load exceeds a safe threshold, do not whole-include by default.

Use a policy buffer:
- reserve some of context for system prompt and user conversation
- reserve some for model response
- only allow whole-artifact expansion into the remaining budget

---

## Artifact Summary Generation

Whole-artifact summary generation should **not** require whole ingestion into the summary model.

### Hierarchical Summary Process
1. Generate a summary for each chunk using the summary model.
2. Preserve the chunk summaries in order.
3. Generate an artifact-level summary from the ordered chunk summaries.
4. Store the final artifact summary as metadata / sidecar, not as a change to artifact text.

This supports:
- large artifacts
- cheaper summary generation
- self-healing maps
- ordered material for later index generation

---

## Artifact Index Generation

The index should be generated in this order of preference:

### Option 1 — Use Existing Headings
If the artifact already contains meaningful headers and the chunking process has identified them, use those as primary structure.

### Option 2 — Infer Scenes / Sections
If meaningful headings do not exist, ask the summary model to divide the work into sections or scenes using the ordered chunk summary list.

For fiction and prose, section boundaries may be inferred from:
- setting changes
- tone shifts
- character focus changes
- plot transitions
- rhetorical or argumentative shifts

### Index Entry Shape
Each index entry should include:
- title / label
- summary
- `chunk_start`
- `chunk_end`

Optional later fields:
- confidence
- heading source (`author_heading` vs `inferred_scene`)
- notes

---

## Self-Healing Metadata

The system should check for summary and index availability during:
- artifact creation
- artifact update
- artifact retrieval / whole-expansion planning

The system should be able to generate missing summary/index metadata on the fly.

### Important Rule
Summary and index metadata are **sidecar metadata**, not artifact content.

Updating summary/index metadata must **not**:
- trigger rechunking
- change the artifact content hash
- create circular update loops

Artifact text identity should be based on readable content only.

---

## Metadata / Persistence Model

### Existing Objects Reused
- artifacts
- corpus_chunks
- retained artifacts
- citation receipts

### New or Expanded Metadata Needed
At minimum, each artifact should expose:
- estimated token count
- chunk count
- summary text
- summary updated timestamp
- summary model id
- index json
- index updated timestamp
- index model id
- artifact text hash

These may live in:
- artifact metadata JSON
- a dedicated artifact sidecar metadata table
- existing sidecar/summary artifacts, depending on implementation choice

### Reading Session Persistence
A new conversation-scoped persistence concept is needed.

Recommended entities:

#### artifact_reading_sessions
Suggested fields:
- id
- conversation_id
- artifact_id
- mode
- status
- strategy_json
- current_section_index
- current_chunk_position
- summary_so_far
- created_at
- updated_at

#### artifact_reading_steps
Suggested fields:
- id
- session_id
- ordinal
- label
- chunk_start
- chunk_end
- status
- notes
- created_at
- updated_at

These are not required for the first implementation if conversation_retained_artifacts is used as a lighter bridge, but they represent the fuller end-state.

---

## Planner Transparency

The planner should not be hidden.

### UX Recommendation
Render planner events inline in the thread as a special scaffold card.

The card should display:
- triggered artifacts
- estimated fit failure
- selected strategy
- what was deferred
- what will happen next

This gives transparency without pretending the planner output is an ordinary assistant reply.

---

## How This Interacts with Retained Artifacts

Retained artifacts remain useful.

For oversized artifacts:
- retain the artifact in the conversation working set
- store carry-forward summary / index references
- remember progression across rounds

The planner can consult retained artifacts and reading progress when deciding whether to:
- continue reading
- switch to another artifact
- revisit a deferred section
- answer using summary vs re-expansion

---

## Web Pages, Long Documents, Stories, Poems, and Technical References

This design works across content classes by changing **strategy**, not architecture.

### Technical Reference / Scientific Paper
Likely strategy:
- summary + index + relevant chunk retrieval

### Short Story / Essay / Long Narrative Web Article
Likely strategy:
- summary + index + sequential staged read if too large

### Poem
Likely strategy:
- whole include if small
- otherwise preserve sequence carefully and avoid topical skimming

### Mixed Set of Large and Small Artifacts
Likely strategy:
- focus on one large artifact
- include smaller artifacts fully or by summary
- defer others explicitly

---

## Potentially Novel / Patent-Relevant Aspects to Discuss with Counsel

This section is descriptive only and not legal advice.

Potentially notable elements:
1. **Capacity-aware planner for whole-artifact inclusion**
2. **Dual-mode artifact processing** (lookup vs reading)
3. **Self-healing artifact maps**
4. **Hierarchical summary-to-index generation**
5. **Conversation-persistent reading plans**
6. **Transparent planner events in conversation threads**
7. **Hybrid strategy planning across multiple artifacts**
8. **Scene inference over chunk summaries**

If counsel wants prior-art research, this section should become the starting claim map rather than final filing language.

---

## Risks

- planner complexity becoming a black box
- over-triggering expensive summaries/index refreshes
- poor scene inference for unusual prose
- over-retaining artifacts and bloating later turns
- confusing users if planner behavior is not surfaced clearly
- circular artifact updates if metadata boundaries are not respected

---

## Recommended First Implementation Slice

1. Add capacity estimation to whole-artifact inclusion path.
2. Add artifact summary/index metadata readiness checks.
3. Implement hierarchical summary generation for large artifacts.
4. Implement index generation using headings first, inferred scenes second.
5. Add planner event rendering to the conversation thread.
6. Add simple reading plan persistence.
7. Use summary + index as fallback whenever full expansion is too large.

---

## Done Means

This subsystem is meaningfully real when:
- the system can detect when whole expansion is too large
- the system can reuse or generate summary/index metadata on demand
- summary/index metadata does not trigger rechunking or hash churn
- the system can plan staged reading for oversized works
- the planner decision is visible to the user
- the system can continue reading later rather than forgetting progress
- the same architecture works for long references and long literary works

---

## Closing

This design turns large-artifact handling from an accidental truncation problem into a deliberate reading strategy system.

It lets WyrmGPT behave less like a search engine pretending to read and more like a context-aware reading assistant that understands its own limits and plans around them.

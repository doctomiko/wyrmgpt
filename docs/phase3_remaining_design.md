# Phase 3 Design — Remaining Work After 3A

## Purpose

After conversation transcript artifacts exist, the rest of Phase 3 turns **memories**, **conversation summaries**, **files**, and **retrieval expansion** into one coherent context-enrichment system.

The goal is:

**source object → artifact → chunks → corpus search → retrieval → optional expansion**

Where source objects may be:

- files
- conversation transcript artifacts
- conversation summary artifacts
- memories

---

## Scope of This Document

This document covers the remaining work after Phase 3A:

- 3B — memories as first-class scoped artifacts
- 3C — retrieval expansion beyond single chunks
- 3D — FULL/FILES mode semantics after memory/conversation enrichment
- 3E — UI and workflow changes needed to manage the new capabilities
- maintenance / backfill / policy considerations

---

## 3B — Memories Become First-Class Scoped Artifacts

### Design intent

Memories should stop being merely injected strings and become proper searchable corpus entities.

### Memory capabilities we want

Each memory should support:

- long-form content
- tags
- importance
- pinned
- archived
- scope
- move
- copy
- delete

### Scope model

Supported scopes for memories:

- `global`
- `project`

Conversation-scoped memories are optional and not needed for the first Phase 3 pass.

### Recommended storage model

Keep memories as source objects, but create one artifact per memory-scope instance.

Examples:

- `memory--<memory_id>--global`
- `memory--<memory_id>--project--<project_id>`

Artifact metadata should include:

- `memory_id`
- `scope_type`
- `scope_id` if project-scoped
- `pinned`
- `importance`
- `archived`
- `tags`
- `memory_updated_at`

### Memory artifact body

Store the memory body exactly as Markdown/plain text, with no decorative prefix unless useful for readability.

Optional heading convention:

```text
[Memory | scope=project:3 | importance=5 | pinned=true | tags=foo,bar]
...memory content...
```

This is optional. Metadata fields may be enough, and retrieval/debug UI can display those values separately.

### Lifecycle hooks

Whenever a memory is:

- created
- edited
- moved
- copied
- archived/unarchived
- pinned/unpinned
- deleted

we must:

1. update or create the corresponding memory artifact(s)
2. re-chunk and reindex them
3. invalidate relevant context caches

### Why long memories are okay

Once memories are chunked and searchable, there is no strong reason to keep them artificially tiny. Long memories become useful notes, bios, research summaries, or canon documents.

### UI implication

The memory editor should support real long-form text. A one-line or tiny input area is no longer enough.

---

## 3C — Retrieval Expansion Beyond Single Chunks

### Problem

Once files, conversation transcripts, and memories are all chunked, a single matching chunk is often not enough.

We need a consistent way for retrieval to suggest when a full source or expanded context should be included.

### Expansion actions to support

Recommended expansion types:

- `include_full_file(file_id)`
- `include_full_memory(memory_id or memory artifact id)`
- `include_conversation_window(conversation_id, around_message_id, before, after)`
- `include_conversation_summary(conversation_id)`
- optional later: `include_full_current_conversation(conversation_id)`

### Retrieval debug additions

Add an `expansion_suggestions` structure to retrieval debug:

```json
{
  "files": [
    {"file_id": "...", "reason": "matched 4 raw chunks"}
  ],
  "memories": [
    {"artifact_id": "...", "reason": "high-confidence memory hit"}
  ],
  "conversation_windows": [
    {"conversation_id": "...", "around_message_id": 1234, "before": 2, "after": 2, "reason": "transcript hit"}
  ],
  "conversation_summaries": [
    {"conversation_id": "...", "reason": "conversation transcript hit"}
  ]
}
```

### Suggested heuristics

#### Full file suggestion
Suggest including full file if:

- raw hits from same file >= configurable threshold
- filename strongly matches shaped query
- top raw file dominates the result set

#### Full memory suggestion
Suggest including full memory if:

- multiple chunks from the same memory artifact match
- memory is pinned or high-importance and has at least one strong hit

#### Conversation window suggestion
Suggest conversation window if:

- hit comes from transcript artifact
- chunk corresponds to a meaningful localized discussion
- surrounding messages likely matter more than the isolated chunk

#### Conversation summary suggestion
Suggest conversation summary whenever a transcript artifact hit is returned, unless the summary is already present in context.

---

## 3D — FULL / FILES Mode Semantics After Enrichment

### Problem

Once memories and transcript artifacts exist, “FILES mode” can no longer literally mean “just files,” unless we want the mode naming to become misleading.

### Proposed semantics

#### `FTS`
Only retrieval-based enrichment.

#### `HYBRID`
Retrieval-based enrichment using lexical + future vector.

#### `FILES`
Include:

- full scoped files
- full scoped memories
- full **current conversation transcript**
- optionally current conversation summary if not already directly present

Do **not** include every transcript from every project conversation in full.

#### `ALL`
Everything from `FILES`, plus retrieval and suggested expansions.

### Project-wide other conversations

For other conversations in the same project:

- include conversation summaries by default
- do not include their full transcripts automatically
- allow retrieval/expansion to pull them in when justified

That keeps the mode useful without exploding context size.

### Policy controls

Recommended config knobs:

- `FULL_INCLUDE_MAX_FILE_CHARS`
- `FULL_INCLUDE_MAX_MEMORY_CHARS`
- `FULL_INCLUDE_MAX_CURRENT_CONVO_CHARS`
- `FULL_INCLUDE_PROJECT_CONVERSATION_SUMMARIES_ONLY = true`
- `FULL_INCLUDE_ALLOW_EXPANDED_OTHER_CONVERSATIONS = true`

---

## 3E — UI / Workflow Changes

### Memory management UI

The memory UI should support:

- create global memory
- create project memory
- edit long content
- tags
- importance
- pinned toggle
- archived toggle
- move to project/global
- copy to project/global
- delete

### Suggested UI improvements

- bigger text area for memory content
- scope dropdown
- tag input
- pinned / archived / important controls
- move/copy actions in memory modal/context menu
- filter/search by tags, project, scope, pinned, archived

### Artifact debug modal

Artifact debug should show source kinds like:

- `file:*`
- `conversation:transcript`
- `conversation:summary`
- `memory`

And include:
- chunk counts
- scope info
- summary links / transcript links
- truncated previews only

### Context panel additions

Once retrieval expansion is implemented, the context panel should show:

- memories in scope
- memories actively included in FULL/FILES mode
- retrieval expansion suggestions
- conversation summaries considered
- conversation windows suggested/included

---

## Conversation Summary Integration

Conversation summaries remain separate artifacts and should **not** be embedded into transcript body.

### On retrieval return for conversation transcript hits

Include:

- `conversation_id`
- `conversation_title`
- `summary_artifact_id`
- `summary_excerpt`
- maybe summary updated timestamp

This lets transcript and summary work together:

- transcript gives local fidelity
- summary gives global overview

---

## Maintenance and Backfill

### Live path first

Before backfilling old data, make live writes correct:

- new messages mark conversation transcript dirty
- new/updated memories update memory artifacts
- new summaries update summary artifacts
- retrieval can see all live-path sources

### Then backfill

After live path is stable:

- backfill existing conversation transcript artifacts
- backfill existing memory artifacts

Do not perform giant backfills at startup.

### Recommended scripts

- `rebuild_conversation_transcripts.py`
- `rebuild_memory_artifacts.py`
- optional `repair_stale_transcript_artifacts.py`

---

## Performance and Safety Policies

### Conversation transcript burden control

- use debounced refresh, not per-message rebuild
- use dirty + lazy repair
- append only new messages
- only full rebuild when artifact missing/corrupt or explicitly requested

### Memory burden control

- long memories are fine, but chunk them
- archived memories should not be included by default in FULL/FILES mode
- archived memories may still be searchable if desired

### Retrieval burden control

- diversify results across source kinds
- suppress file chunks from final prompt when full file already included
- same idea later for memories: suppress memory chunks when full memory already included

---

## Recommended Phase 3 Order After 3A

### 3B.1
Memory schema/UI cleanup:
- scope
- pinned
- archived
- tags
- importance

### 3B.2
Memory artifactization:
- create/update/delete hooks
- chunking and indexing

### 3C.1
Retrieval expansion suggestions:
- files
- memories
- conversation windows
- conversation summaries

### 3D.1
Broaden FULL/FILES mode:
- full scoped files
- full scoped memories
- full current conversation transcript

### 3E.1
UI upgrades:
- memory editor/modal
- artifact debug visibility
- context panel additions

### 3E.2
Backfill and repair scripts

---

## Non-goals for the Immediate Phase 3 Remainder

Do not attempt all of these at once:

- automatic inclusion of every project conversation transcript
- fancy vector search before lexical path is mature
- complex cross-project memory graph logic
- full transcript export for every source type
- retroactive rewriting of transcript canonical A/B markers on every Use click

---

## Final Recommendation

Phase 3 should make **conversation transcripts, conversation summaries, memories, and files all first-class artifact sources**, then make retrieval smart enough to expand from chunk-level matches into the full source when justified.

That is the point where RAG becomes the main context engine instead of a bolt-on.

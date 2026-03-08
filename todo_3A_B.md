# TODO 3A.B — Deferred Items After 3A Core Transcript Artifacts

This note preserves the things intentionally deferred while implementing Phase 3A so they are not forgotten later.

---

## 1. 3A.5 Real Tail-Only Rechunking

### Current state

The current implementation lays the rail for tail-only rechunking with a wrapper such as:

- `reindex_conversation_transcript_artifact(...)`

and metadata flags such as:

- `chunking_mode`
- `tail_rechunk_ready`

Today that wrapper still falls back to a full artifact reindex.

### What remains to do

Implement a true tail-only rechunk path for large conversation transcript artifacts.

### Desired behavior

- Keep existing early chunks when the transcript grows.
- Recompute only the transcript tail from the last safe chunk boundary forward.
- Update corpus chunk rows only for the affected tail section.
- Preserve earlier stable chunk rows and FTS coverage.

### Suggested metadata additions if needed later

- `last_safe_chunk_start_offset`
- `last_safe_chunk_index`
- `last_safe_message_id`
- `tail_rechunk_strategy_version`

### When to do this

Only after observing that full transcript reindexing is actually expensive enough to matter in production.

---

## 2. Style Summary Messages Differently in the Chat UI

### Current state

Summary assistant messages are intentionally excluded from transcript artifacts because:

- the conversation summary already exists as its own artifact
- embedding summary text in transcript body would create duplication
- retrieval can join summary text when transcript hits are returned

### What remains to do

In the visible chat UI, style summary output messages differently from normal assistant replies.

### Suggested behavior

- detect summary messages by message metadata, e.g. `meta.summary === true`
- apply a distinct CSS class such as `.msg.summaryMessage`
- optionally add a subtle label like `Summary` in the message header
- keep the content readable but visually distinct from ordinary conversation turns

### Why this matters

It helps users distinguish:

- ordinary assistant replies
- assistant summary artifacts that were emitted into the visible chat stream

without confusing those UI messages with transcript content.

---

## 3. FULL / FILES Prompt Inclusion for Transcript Artifacts

### Current state

Transcript artifacts are now:

- refreshable
- exportable
- searchable
- lazy-repaired
- retrievable with summary join metadata

But they are **not yet** included automatically into prompt assembly in FULL / FILES mode.

### What remains to do

Define and implement transcript inclusion semantics as part of later Phase 3D.

### Recommended direction

For FULL / FILES style modes:

- include full scoped files
- include full scoped memories
- include the **full current conversation transcript**
- include other project conversations by **summary only** unless retrieval explicitly asks for transcript expansion

### What not to do

Do not automatically include full transcript history for every project conversation in scope. That is likely to bloat prompt size badly.

### Why this is deferred

The transcript artifact layer should first prove itself as a searchable retrieval source before becoming an always-include source in larger context modes.

---

## 4. Optional Later Reconciliation of Canonical A/B Markers

### Current state

The transcript policy intentionally preserves both A and B assistant responses when they were shown to the user.

If canonical information is available at transcript build time, it may be written into the header. But the transcript is **not** rewritten retroactively every time the user clicks `Use` later.

### What remains to do

If desired later, allow a **full rebuild from SQL** to reconcile canonical markers for older A/B transcript headers.

### Why this stays deferred

Incremental transcript maintenance should stay cheap.
Retroactive transcript rewrites on every later `Use` action are not worth the complexity right now.

---

## 5. Optional Transcript Export Enhancements

### Current state

Conversation transcript export is planned as Markdown.

### What remains to do later

Possible enhancements:

- JSON export alongside Markdown
- include export manifest metadata
- include summary excerpt in sidecar metadata, not body
- export conversation diagnostics separately if useful for research workflows

---

## Bottom Line

3A core should focus on:

- one conversation transcript artifact per conversation
- dirty marking on message insert
- lazy repair and stale detection
- incremental append
- transcript export
- searchable retrieval with summary join metadata

The items in this document are intentionally deferred so the first implementation stays stable, readable, and cheap enough to operate.

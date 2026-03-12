# Phase 3A Design — Conversation Transcript Artifacts (3A–3A.5)

## Purpose

Make conversation history a first-class retrieval source by maintaining **one canonical transcript artifact per conversation**, stored as human-readable Markdown, chunked for search, and refreshed lazily instead of on every message.

This replaces the earlier idea of “one message = one artifact.” The artifact will contain a readable transcript of the conversation, not raw JSON, and will support chunk retrieval plus expansion to surrounding context.

---

## Agreed Principles

- One **conversation transcript artifact** per conversation.
- The artifact body is a **human-readable Markdown transcript**.
- Conversation **summary is not embedded in the transcript body**. It is linked in metadata and joined on retrieval.
- The transcript artifact is updated **incrementally** by appending only new messages when possible.
- We do **not** regenerate the whole conversation artifact on every new message.
- We use a **dirty flag + lazy repair**, plus an explicit client-side debounce/flush trigger.
- We also support a **cheap server-side stale check** against SQL so missed client flushes are repaired.
- We strip **Zeitgeber hints** from message body text before appending, because timestamps will be carried in the transcript header.
- We preserve **both A and B assistant replies** in the transcript. If canonical choice information is known at build time, include it in the header. Do not rewrite old transcript content just because “Use” is clicked later, unless a full rebuild happens from scratch.
- Summary output messages posted into the visible chat stream should be **excluded** from transcript artifacts.
- We want an **Export Transcript** menu action for conversations.
- UTC timestamps remain in headers for precision, but we also include a **local human-readable timestamp**.

---

## Artifact Identity and Metadata

Each conversation gets one deterministic transcript artifact:

- `artifact_id = "conversation-transcript--<conversation_id>"`
- `source_kind = "conversation:transcript"`
- `source_id = <conversation_id>`
- `scope_type = "conversation"`
- `scope_uuid = <conversation_id>`

### Metadata to store with the artifact

Recommended in `artifacts.meta_json` (or equivalent metadata field if one already exists):

- `conversation_id`
- `conversation_title`
- `transcript_format_version`
- `dirty` (bool)
- `last_message_id_indexed`
- `last_message_created_at_utc`
- `message_count_indexed`
- `summary_artifact_id` (if present)
- `summary_updated_at` (optional cache)
- `has_ab_messages` (optional)
- `last_incremental_append_at`
- `last_full_rebuild_at`
- `last_staleness_check_at`
- `local_timezone` used for human-readable timestamps

### Why metadata matters

This lets us:

- append only newer messages
- detect staleness without pulling the full transcript
- join conversation summary when retrieval returns transcript hits
- support later optimizations like tail-only rechunking

---

## Transcript Body Format

The artifact body is plain Markdown text, readable by humans and the LLM.

### Header convention

Each message block starts with a single-line header like:

```text
[User | user=alice | msg_id=123 | 2026-03-07T12:34:56Z | Fri 2026-03-07 07:34:56 EST]
...message markdown...
```

```text
[Assistant A | provider=OpenAI | model=gpt-5.4 | canonical=false | msg_id=124 | 2026-03-07T12:35:02Z | Fri 2026-03-07 07:35:02 EST]
...assistant response A markdown...
```

```text
[Assistant B | provider=OpenAI | model=gpt-5.4 | canonical=true | msg_id=125 | 2026-03-07T12:35:02Z | Fri 2026-03-07 07:35:02 EST]
...assistant response B markdown...
```

```text
[System Message | msg_id=126 | 2026-03-07T12:35:03Z | Fri 2026-03-07 07:35:03 EST]
...error/status text...
```

### Rules

- Preserve the **message body exactly as Markdown**.
- Strip Zeitgeber line(s) from the body before writing.
- Include optional user identity only if known:
  - `user=<display_name>`
  - `user_id=<id>` only if useful and available
- Use consistent role labels:
  - `User`
  - `Assistant A`
  - `Assistant B`
  - `Assistant`
  - `System Message`
- If canonical A/B choice is known **at transcript build time**, include `canonical=true/false`.
- Do **not** mutate historical transcript text later just because the user clicked “Use” retroactively.
- On a future full rebuild from SQL, canonical markers may be recomputed if the data model supports it.

### Exclusions

Do **not** append these into the transcript artifact:

- system prompt text
- hidden/debug context payloads
- summary output messages posted into chat as part of summarize actions
- purely structural internal events with no user-facing meaning

---

## Dirty + Lazy Repair Model

### On every new message insert

Do **not** rebuild the transcript artifact immediately.

Instead:

1. mark transcript artifact metadata `dirty = true`
2. update:
   - `latest_message_id_seen`
   - `latest_message_created_at_seen`
3. optionally enqueue a cheap in-memory “conversation needs refresh” hint

This keeps message insert cheap.

### Client-side triggers

When the user is viewing a conversation:

- debounce a flush request after **1–5 minutes** of inactivity (start at 90 seconds or 120 seconds)
- when the user switches away from the conversation, fire-and-forget a refresh request
- when the tab/page is closing, try `sendBeacon()` or `fetch(..., keepalive=True)` as a best-effort flush

### Server-side safety net

Any server path that needs accurate transcript/search data may lazily repair first:

- context build
- RAG retrieval for that conversation
- artifact debug / scoped artifact inspection
- transcript export
- optional summarize flow

If transcript artifact is marked dirty or SQL indicates it is stale, refresh it before continuing or queue a repair.

---

## Fast Staleness Detection

We want a cheap query that avoids reading the entire transcript body.

### Primary checks

A transcript artifact is stale if **any** of these are true:

- metadata `dirty = true`
- the latest SQL `messages.id` for the conversation is greater than `last_message_id_indexed`
- optionally, the latest SQL `messages.created_at` is newer than the artifact’s `updated_at`

### Practical recommendation

Use message ID first. It is cheaper and less ambiguous than timestamp comparisons.

### Example conceptual query

```sql
SELECT
  c.id AS conversation_id,
  a.id AS artifact_id,
  MAX(m.id) AS latest_message_id,
  MAX(m.created_at) AS latest_message_created_at,
  json_extract(a.meta_json, '$.last_message_id_indexed') AS last_indexed_id,
  a.updated_at AS artifact_updated_at
FROM conversations c
LEFT JOIN artifacts a
  ON a.source_kind = 'conversation:transcript'
 AND a.source_id = c.id
 AND a.is_deleted = 0
LEFT JOIN messages m
  ON m.conversation_id = c.id
GROUP BY c.id, a.id
HAVING
    a.id IS NULL
 OR CAST(COALESCE(json_extract(a.meta_json, '$.last_message_id_indexed'), 0) AS INTEGER) < COALESCE(MAX(m.id), 0)
 OR COALESCE(json_extract(a.meta_json, '$.dirty'), 0) = 1;
```

### Optimization notes

- The `MAX(messages.id)` path is the best default stale check.
- Timestamp comparison is optional backup.
- This query can power a “repair stale transcript artifacts” maintenance pass later.

---

## Incremental Append Strategy

### The normal refresh path

When refreshing one conversation transcript artifact:

1. load artifact metadata
2. read `last_message_id_indexed`
3. query only:
   - `SELECT * FROM messages WHERE conversation_id = ? AND id > ? ORDER BY id ASC`
4. render those messages into transcript blocks
5. append to existing artifact content
6. update metadata:
   - `last_message_id_indexed`
   - `last_message_created_at_utc`
   - `message_count_indexed`
   - `dirty = false`
7. re-chunk and reindex the transcript artifact

### Important constraint

Do **not** re-read all prior messages during incremental append.

### If the artifact is missing or corrupted

Do a full rebuild:

1. read all messages for the conversation
2. render full transcript body
3. replace artifact content entirely
4. reset metadata
5. re-chunk and reindex

---

## Chunking Strategy

### Day-one strategy

Use the existing chunker against the **whole transcript artifact** whenever the transcript is refreshed.

That is acceptable because refreshes are debounced and append-based, not per-message.

### Later optimization (3A.5)

If full rechunking becomes too expensive, add tail optimization:

- store safe chunk boundary metadata in `meta_json`
- on append, rebuild only from the last stable chunk boundary forward
- preserve unchanged earlier chunk rows if feasible

This is explicitly an optimization, not required for the first implementation.

---

## Retrieval Behavior for Conversation Hits

When retrieval returns a chunk from a conversation transcript artifact, the returned metadata should include:

- `conversation_id`
- `conversation_title`
- `conversation_summary_artifact_id` if present
- `conversation_summary_excerpt` if available
- `artifact_kind = conversation:transcript`

Later, retrieval should be able to suggest:

- include surrounding transcript chunks
- include a ±N message window
- include the conversation summary
- include the full current conversation transcript in FULL/FILES mode

---

## A/B Message Policy

We explicitly preserve both A and B transcript text because:

- users do not always click Use religiously
- both branches were actually shown and read
- transcript readability matters for AI research workflows
- retroactively mutating transcript text for every later Use action is not worth the effort during incremental maintenance

### Policy

- append both A and B when they occurred
- if the selected branch is already known when refreshing, mark canonical in header
- do not rewrite historical transcript text later for retroactive Use actions during incremental append
- a future full rebuild from SQL may reconcile canonical state if desired

---

## Export Transcript

Add a conversation menu action:

- `Export Transcript`

Behavior:

- ensure transcript artifact is refreshed first
- export human-readable Markdown transcript
- optionally support `.md` download immediately
- future enhancement: export JSON alongside Markdown

The export should use the transcript artifact body, not re-render from scratch unless refresh was needed.

---

## Chat Summary Message Handling

Summary assistant messages that are posted into the visible chat stream are useful for users, but should be excluded from transcript artifacts.

### Why

- the summary already exists as its own artifact
- including it in transcript text creates duplication
- retrieval can join the summary artifact when a conversation transcript hit occurs

### UI note

Style visible summary messages differently from normal chat messages in the frontend.

---

## Performance / Policy Controls

Recommended config knobs:

- `CONVO_TRANSCRIPT_REFRESH_IDLE_SEC`
- `CONVO_TRANSCRIPT_REBUILD_ON_CONTEXT = true/false`
- `CONVO_TRANSCRIPT_FULL_RECHUNK_POLICY = ALWAYS | DIRTY_ONLY`
- `CONVO_TRANSCRIPT_EXPORT_REPAIR = true`
- `CONVO_TRANSCRIPT_MAX_APPEND_BATCH_MESSAGES`
- `CONVO_TRANSCRIPT_STRIP_ZEITGEBER = true`
- `CONVO_TRANSCRIPT_LOCAL_TIMEZONE`

Recommended starting defaults:

- idle refresh: 90–120 sec
- repair on context/retrieval: true
- export repair: true
- strip Zeitgeber: true

---

## Implementation Sequence (3A–3A.5)

### 3A — Core transcript artifact
- add transcript artifact id helper
- add metadata support (`meta_json` or equivalent)
- add dirty marking on message insert
- add full rebuild helper
- add incremental append helper

### 3A.1 — Lazy repair endpoint
- `POST /api/conversation/{conversation_id}/refresh_transcript_artifact`

### 3A.2 — Client debounce and conversation-switch flush
- idle timer
- on conversation switch
- best-effort unload flush

### 3A.3 — Retrieval integration
- include transcript artifact hits in RAG result metadata
- join summary metadata

### 3A.4 — Export Transcript
- add left-pane menu action
- download `.md`

### 3A.5 — Tail-only rechunk optimization
- optional later optimization if needed

---

## Non-goals for the First Pass

Do **not** do these in the first 3A pass:

- per-message artifacts
- rewriting old transcript text every time canonical A/B choice changes
- embedding conversation summary text into transcript body
- project-wide full conversation history inclusion by default
- complex partial chunk row surgery unless performance forces it

---

## Final Recommendation

Implement transcript artifacts first, then memories.

This gives the system a stable, human-readable, searchable representation of conversation history without per-message artifact churn, while leaving room for later optimization and richer expansion behavior.

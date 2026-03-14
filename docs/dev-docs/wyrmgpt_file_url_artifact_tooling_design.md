# WyrmGPT File / URL / Artifact / Tooling Design

## 1. Goals and Scope

We’re extending WyrmGPT with a proper notion of:

- Files uploaded from the UI (chat-scoped, project-scoped, sandboxed, or global)
- URL-derived content
- Artifacts (the canonical, model-visible chunks of text)
- Tools that the model can invoke via explicit syntax, which the backend executes

Constraints:

- We must respect the existing schema in `server/db.py` (no destructive changes), and add migrations for new fields.
- Projects use integer IDs (`projects.id`), conversations use text IDs (`conversations.id`, UUID-style). We need to handle both cleanly.
- The LLM never directly sees raw files or URLs, only artifacts and pinned/memory text.
- Context building needs a cache, invalidated when new files/URLs/memories are introduced.

This doc is the design; code changes come after you sign off.

---

## 2. Existing Data Model (Relevant Bits)

From `server/db.py` `_apply_schema_v2` we already have:

- `projects`
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `uuid TEXT UNIQUE`
  - `name`, `description`, `system_prompt`, flags, timestamps

- `conversations`
  - `id TEXT PRIMARY KEY` (UUID-ish)
  - `project_id INTEGER`
  - `title`, `summary_json`, `archived`, timestamps

- `messages`
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `conversation_id TEXT NOT NULL`
  - `role`, `content`, timestamps, `meta`

- `files`
  - `id TEXT PRIMARY KEY`
  - `name TEXT NOT NULL`
  - `path TEXT NOT NULL`
  - `mime_type TEXT`
  - `created_at`, `updated_at`

- `project_files`
  - `project_id INTEGER NOT NULL`
  - `file_id TEXT NOT NULL`
  - PK `(project_id, file_id)`

- `memories`
  - `id TEXT PRIMARY KEY`
  - `content TEXT NOT NULL`
  - `importance INTEGER`
  - `tags TEXT`
  - timestamps

- `memory_projects`
  - `memory_id TEXT`
  - `project_id INTEGER`

- `memory_conversations`
  - `memory_id TEXT`
  - `conversation_id TEXT`

- `artifacts`
  - `id TEXT PRIMARY KEY`
  - `project_id INTEGER NOT NULL`
  - `name TEXT NOT NULL`
  - `content TEXT NOT NULL`
  - `tags TEXT`
  - `updated_at`

So: we already have the conceptual buckets, but they are project-only; nothing knows about chat-scoped files/artifacts, sandbox/global scope, URLs, or provenance. There is no cache table yet.

---

## 3. Concepts and Vocabulary

We’ll lock in these meanings:

- **File**  
  A piece of content stored under WyrmGPT’s control on disk, referenced by a `files` row. Source may be an upload, a fetched URL, or a tool-generated artifact. The backend can `open(path)`.

- **URL**  
  A locator string like `https://doctorwyrm.com/...`. The backend can fetch it and write the response into a file. The model only ever sees text artifacts derived from that fetch, not the URL itself unless we choose to show it.

- **Artifact**  
  The canonical unit of model-visible context: a chunk of text (or summary, note, memory, etc.) plus metadata. Artifacts may be backed by a file or derived from conversation or URL. Context building deals in artifacts, not files/URLs.

- **Scope**  
  Where this thing “lives” logically: `"chat"`, `"project"`, `"sandbox"`, or `"global"`. Because projects use integer IDs and conversations use UUID/text IDs, we’ll support both as potential scope keys.

- **Provenance**  
  A human-oriented text memo about where the thing came from: “Uploaded via chat 1234 on 2026-02-27” or “Fetched from https://…”. This can be injected into context when useful.

- **Tool**  
  A named backend capability exposed to the model via explicit syntax (e.g. `<<tool:fetch_url {...}>>`), described in a JSON tool catalog. The model may *ask* to use tools; only the backend actually executes them.

---

## 4. High-Level Flows

### 4.1 Use Case 1: Add Files from Chat

User clicks a “+” button next to the chat input → “Add Files” dialog:

- User selects one or more files via the browser file picker.
- User picks scope:
  - “This chat only”
  - “This project”
  - “Sandbox” (future)
  - “Global”

For now we’ll implement “chat” and “project”, with “global” as an internal default when no project/chat is specified.

Backend behavior:

1. Accept upload via multipart POST.
2. For each file:
   - Copy it into a canonical path under the data root, e.g.:

     - `<root>/data/sources/chats/<conversation_id>/…`
     - `<root>/data/sources/projects/<project_id>/…`
     - `<root>/data/sources/global/…`
     - `<root>/data/sandbox/<sandbox_id>/…` (future)

     The physical path is just stored in `files.path`; scope lives in columns, not in the path semantics.

   - Insert/update a `files` row with scope and provenance.
   - Insert linking rows as needed (`project_files`, and future `conversation_files`/`sandbox_files`).
3. Trigger artifactization:
   - Text extraction for text/PDF
   - OCR/image captioning if/when available
   - Chunking into one or more `artifacts` rows linked to the same scope and project/chat.
4. Invalidate any context cache for that conversation and project.

The original local path on the user’s machine is not stored.

### 4.2 Use Case 2: Add Files from Project Context

Same pipeline, different default:

- User right-clicks a project in the left rail → “Add Files to Project”.
- Scope defaults to `"project"` with `scope_id = projects.id`.
- The file is not bound to any specific conversation unless the UI explicitly provides that later.

Internally this hits the same upload endpoint with different scope parameters.

### 4.3 Use Case 3: URL-Based Files

User or model wants to ingest a URL:

- From the UI: a future “Add URL” dialog lets the user paste a URL and choose scope.
- From the model: the LLM emits a tool token like:

  `<<tool:fetch_url {"url": "https://example.com/page", "scope_type": "project", "scope_id": 3}>>`

Backend behavior for URL ingestion:

1. Validate and normalize the URL.
2. Fetch it with an HTTP client, following redirects.
3. Persist response content as a file under something like `<root>/data/sources/url/<hash>.html` (or `.txt` for simplified text).
4. Insert a `files` row:

   - `source_kind = "url"`
   - `url` set to the source URL
   - `scope_type`/`scope_id`/`scope_uuid` per requested scope
   - provenance like “Fetched via fetch_url tool from https://… on …”

5. Run the same artifact pipeline as uploads.
6. Invalidate context cache for affected scopes.

Again: URL → file → artifact. The model only ever sees artifacts.

---

## 5. Data Model Changes

We add columns/tables; we don’t drop or redefine existing ones.

### 5.1 `files` Table Extensions

Current:

- `id TEXT PRIMARY KEY`
- `name TEXT NOT NULL`
- `path TEXT NOT NULL`
- `mime_type TEXT`
- `created_at`, `updated_at`

Proposed additions:

- `scope_type TEXT`  
  `"chat" | "project" | "sandbox" | "global"`. For legacy rows we’ll backfill `"project"` or `"global"`.

- `scope_id INTEGER`  
  For integer-backed scopes (e.g. `projects.id`).

- `scope_uuid TEXT`  
  For text/UUID scopes (e.g. `conversations.id`).

- `source_kind TEXT`  
  `"upload" | "url" | "tool" | "system"`; helps for debugging and later policy decisions.

- `url TEXT`  
  Nullable; populated when `source_kind = "url"`.

- `provenance TEXT`  
  Free-text memo. E.g. “Uploaded from chat 8f62… in project 3 on 2026-02-27.”

- `is_deleted INTEGER NOT NULL DEFAULT 0`
- `deleted_at TEXT`
- `deleted_by_user_id TEXT` (or `deleted_by TEXT` as a string for now, since we don’t have a users table yet)

Existing `project_files` remains and can co-exist: `files.scope_*` capture primary/obvious scope; `project_files` allows explicit many-to-many associations when a file belongs to multiple projects.

Migration behavior:

- For each existing `files` row that has an entry in `project_files`:
  - `scope_type = "project"`
  - `scope_id = project_id`
- If a file is linked to multiple projects, we either:
  - Pick the first as primary in `files.scope_id` and keep the rest only via `project_files`, or
  - Leave `scope_type = "global"` and rely entirely on `project_files`.
- For unlinked files, default `scope_type = "global"` and leave IDs null.

### 5.2 `artifacts` Table Extensions

Current:

- `id TEXT PRIMARY KEY`
- `project_id INTEGER NOT NULL`
- `name TEXT NOT NULL`
- `content TEXT NOT NULL`
- `tags TEXT`
- `updated_at`

Proposed additions:

- `scope_type TEXT`  
  Same idea as `files.scope_type` — where this artifact “lives” logically.

- `scope_id INTEGER`  
  For project/sandbox integer scopes.

- `scope_uuid TEXT`  
  For chat-scoped artifacts and future UUID scopes.

- `file_id TEXT`  
  Nullable foreign key to `files.id` when this artifact is derived from a file or URL.

- `source_kind TEXT`  
  `"file_chunk" | "url_chunk" | "memory" | "summary" | "note" | "tool"`, etc.

- `provenance TEXT`  
  Optional human-readable origin note.

- `is_deleted INTEGER NOT NULL DEFAULT 0`
- `deleted_at TEXT`
- `deleted_by_user_id TEXT`

We keep `project_id` for backward compatibility and as a fast filter. For non-project scopes, `project_id` may be null; in those cases `scope_type` + `scope_uuid`/`scope_id` tells us where it belongs.

Migration:

- For existing artifacts:
  - `scope_type = "project"`
  - `scope_id = project_id`
  - `scope_uuid = NULL`
  - `file_id = NULL`
  - `source_kind = "legacy"`
  - `provenance = NULL`

### 5.3 Optional New Link Tables

To keep many-to-many relationships explicit and clean, we can introduce:

- `conversation_files`
  - `conversation_id TEXT NOT NULL`
  - `file_id TEXT NOT NULL`
  - PK `(conversation_id, file_id)`

- `conversation_artifacts`
  - `conversation_id TEXT NOT NULL`
  - `artifact_id TEXT NOT NULL`
  - PK `(conversation_id, artifact_id)`

These mirror `project_files` and `project_imports`. The `scope_*` columns give us a “primary attachment,” and the link tables allow us to attach the same file/artifact to multiple conversations if needed.

We don’t have to introduce these immediately to get basic chat/project scoping working, but they’re a clean long-term shape. For now, we can start by:

- Using `files.scope_type` + scope ID/UUID for the default association.
- Using `project_files` as the way to attach files to projects from project UI.

### 5.4 Context Cache Table

We add a new table to support cached context building:

- `context_cache`
  - `conversation_id TEXT PRIMARY KEY`
  - `project_id INTEGER`
  - `cache_key TEXT NOT NULL DEFAULT 'default'` (future-proofing if we want multiple variants)
  - `payload TEXT NOT NULL` (JSON blob: precomputed context sources, artifact IDs, snippet list, etc.)
  - `updated_at TEXT NOT NULL`

For now, we’ll treat `cache_key = 'default'` as the only mode, and cache the computed context sources we currently build in `get_context_sources` / `build_context`.

Invalidation rules (initial):

- On new message in a conversation → invalidate cache for that conversation.
- On new memory / pinned memory for that project or conversation → invalidate relevant caches.
- On new file/URL/artifact associated with the conversation/project → invalidate relevant caches.
- A relevant tool result explicitly marks the cache as stale (e.g. `curate_memory` tool).

We can start simple: whenever we mutate anything that could affect context, we call `invalidate_context_cache(conversation_id, project_id)`.

---

## 6. Tooling Design

### 6.1 Tool Catalog JSON

We follow the pattern of `server/model_catalog.json` and add `server/tool_catalog.json` with entries like:

```json
{
  "fetch_url": {
    "display_name": "Fetch URL",
    "description": "Fetches the content of an HTTP(S) URL, stores it as a file, and creates artifacts for use in context.",
    "enabled": true,
    "endpoint": "/api/tools/fetch_url",
    "method": "POST",
    "params": {
      "url": { "type": "string", "required": true },
      "scope_type": { "type": "string", "required": false },
      "scope_id": { "type": "integer", "required": false },
      "scope_uuid": { "type": "string", "required": false }
    },
    "system_usage": "Use this tool when the user explicitly asks you to read or ingest a specific web page. Do not use it for arbitrary browsing."
  },
  "curate_memory": {
    "display_name": "Curate Memory",
    "description": "Stores a long-term memory plus tags and importance, linked to the current project and conversation.",
    "enabled": true,
    "endpoint": "/api/tools/curate_memory",
    "method": "POST",
    "params": {
      "content": { "type": "string", "required": true },
      "tags": { "type": "string", "required": false },
      "importance": { "type": "integer", "required": false }
    },
    "system_usage": "Use this tool to store facts that will remain true and relevant in future conversations."
  }
}
```

This gives us:

- A structured description for the system prompt (we can inject `system_usage` and `params` as part of the prompt when tools are enabled).
- A mapping from tool name to HTTP endpoint and parameters.

Later we can add an “enabled/disabled per project” layer stored in the DB; for now, if a tool exists and `enabled: true` in JSON, it’s usable.

### 6.2 Tool Python Modules

We add a `tools/` package at the repo root, parallel to `server/`:

- `tools/__init__.py`
- `tools/fetch_url.py`
- `tools/curate_memory.py`
- etc.

Each tool module exposes a simple callable that expects a dict of parsed parameters and a DB/session context. The HTTP layer in `server/main.py` just:

- Validates incoming JSON against `tool_catalog.json` param schema.
- Calls the appropriate tool function.
- Returns a JSON result (success/failure, created IDs, etc.).

This separates:

- HTTP/glue code (in `server/main.py`)
- Tool logic (in `tools/*.py`)
- Tool metadata (in `server/tool_catalog.json`)

### 6.3 Tool Invocation Syntax

We define a strict syntax that only the model is supposed to use, not the user:

- `<<tool:TOOL_NAME {JSON_PAYLOAD}>>`

Example:

- `<<tool:fetch_url {"url": "https://doctorwyrm.com/2026/02/the-calliope-method/", "scope_type": "project", "scope_id": 3}>>`
- `<<tool:curate_memory {"content": "Tomiko prefers bourbon over rye in most contexts.", "tags": "preferences,alcohol", "importance": 5}>>`

The backend:

1. Scans model outputs for `<<tool:...>>` tokens.
2. Parses the JSON payload.
3. Looks up `TOOL_NAME` in `tool_catalog`.
4. Validates params.
5. Executes the corresponding tool endpoint or internal handler.
6. Optionally injects a follow-up assistant message summarizing what happened (“I’ve ingested that page and will now use it for context.”).

Users cannot directly send this syntax in the UI; or if they do, we treat it as plain text unless the assistant chooses to echo a tool trigger.

---

## 7. Context Building and Caching

### 7.1 Current Behavior (High-Level)

Right now, `get_context_sources(conversation_id)`:

- Loads conversation + project metadata and system prompt.
- Pulls pinned manual memories (`memory_pins`).
- Pulls machine memories (`memories` + `memory_projects`/`memory_conversations`).
- Builds a `summary` based on `summary_json`.
- `build_context` then produces a system message with:
  - System prompt
  - Pinned memories section
  - Conversation summary
  - Retrieved memories section
- Then appends recent message history.

No files/artifacts are in play yet; no cache.

### 7.2 New Behavior

We want context building to consider:

- Pinned/manual memories.
- Machine memories.
- Relevant artifacts (derived from files/URLs).
- Possibly tool output later.

The process (conceptual):

1. See if there is a valid context cache entry for this conversation and the default key.
2. If cached, load `payload` JSON and unpack:
   - Selected memory IDs
   - Selected artifact IDs
   - Any preformatted text snippets
3. If not cached:
   - Query memories (`memories`, `memory_projects`, `memory_conversations`) as now.
   - Query artifacts:
     - Filter by project_id and/or scope matching this conversation/project.
     - (Later: apply embeddings or simple keyword matching to pick relevant ones.)
   - Build the context sections (as strings or structured objects).
   - Serialize them into `payload` and write `context_cache`.
4. Build the final system message from:
   - Core or project system prompt
   - Pinned memories text
   - Conversation summary
   - Retrieved memories text
   - Any artifact excerpts (“Attached context from files:”)

### 7.3 Cache Invalidation Rules

We invalidate cached context for a conversation when any of the following happens:

- A new message is added to that conversation (most conservative, and simplest initial behavior).
- A pinned memory is added/edited/deleted.
- A new memory is created or linked to the project/conversation.
- A file or URL is uploaded/ingested and artifacts are created for the same project or conversation.
- A relevant tool result explicitly marks the cache as stale (e.g. `curate_memory` tool).

Implementation-wise:

- Add a helper in `db.py`: `invalidate_context_cache(conversation_id: str)` that deletes `context_cache` rows for that conversation.
- Optionally: support project-level invalidation if we introduce project-scoped caches.

---

## 8. Deletion and Soft-Delete Semantics

We are not implementing delete UX yet, but we design for it:

- `files`, `artifacts`, `memories` get:
  - `is_deleted`, `deleted_at`, `deleted_by_user_id`.
- Queries that feed context, lists, etc., must filter on `is_deleted = 0`.
- Deletion from the UI:
  - Marks rows as deleted.
  - Optionally cleans up associated links (`project_files`, `memory_*`, `conversation_files`).
  - Invalidates the context cache.

We do **not** physically unlink or delete the filesystem files initially; that can be a later “garbage collector” concern once we’ve lived with the system a bit.

---

## 9. Summary of Key Design Decisions

To make sure we’re aligned before writing code:

- Files and URLs live only in “backend reality”. The model never sees them directly.
- Artifacts are the only units of context the model sees, and they are linked back to files/URLs/memories via IDs and provenance.
- Scope is explicit: `scope_type`, plus `scope_id` (int) and `scope_uuid` (text) so we can handle project vs conversation cleanly.
- Existing schema is extended, not broken:
  - `files` and `artifacts` gain new columns; we add new tables like `context_cache` and optionally `conversation_files`.
  - `project_files` and the rest remain intact.
- Tools are defined declaratively in `server/tool_catalog.json`, implemented in `tools/*.py`, and invoked via strict `<<tool:...>>` syntax only by the assistant, never blindly by user input.
- Context building gains a cache, with invalidation on any state change that could affect what context we should show.

If you’re good with this shape, next step is:

1. Update the DB schema and migration story in detail (which columns, which `ALTER TABLE`s, how we backfill).
2. Sketch the new file upload API and URL fetch tool endpoints.
3. Wire just enough frontend to support “Add Files” from chat/project with the new backend contracts.

But first: sanity check this doc. Anything here feel wrong to you before we start cutting into `db.py` and `main.py`?

# WyrmGPT File Artifacting & Context Design (Phase 2)

_Last updated: 2026-02-27_

This document defines the design for the **Artifactor** pipeline in WyrmGPT: how uploaded files become artifacts, how those artifacts are chunked and scoped, and how they will feed into the context builder.

The goal is to:
- Treat files as first-class resources with clear **scope** (conversation / project / global).
- Convert files into **artifacts** (text and image descriptors) in a reusable, API-driven way.
- Support **re-artifacting** (upsert semantics) when files change.
- Prepare for future tools (e.g., Callie Connector) to call this API instead of re-implementing artifacting logic.

This design assumes the current DB and file upload system as of the `fileuploadmostlydone_wyrmgpt.zip` build, plus the previous file/url tooling design doc.

---

## 1. Concepts & Terminology

**File**  
A file on disk, uploaded or otherwise registered into the `files` table. It has:
- A unique `id` (UUID-like string).
- A `name`, `path`, `mime_type`.
- Scope metadata: `scope_type`, `scope_id`, `scope_uuid`.
- Other metadata: `source_kind`, `url`, `provenance`, `description`, soft-delete fields.

A file can be:
- **Conversation-scoped** – relevant only to one chat.
- **Project-scoped** – relevant to all conversations in a project.
- **Global-scoped** – available to any conversation (e.g., shared docs).

**Artifact**  
A chunk of content derived from a file (or later, from other tools). It lives in the `artifacts` table and stores:
- Content (usually text; in some cases JSON describing images).
- Linkage: `project_id`, `file_id`, `scope_type`, `scope_id`, `scope_uuid`, `source_kind`, `provenance`.
- Soft-delete flags.
- A positional `chunk_index` indicating its order among siblings for the same file.

**Artifactor**  
A pure-Python module that, given a file row, reads the file, converts it to text (or image descriptor), chunks it, and writes artifacts.

The Artifactor:
- Is idempotent per file: re-artifacting a file replaces the previous artifact set for that file (via soft-delete).
- Has file-type specific handlers (ZIP, PDF, DOCX, text, images, code).
- Exposes a small API surface in Python and via FastAPI endpoints.

**Context Builder**  
Existing logic that collects conversation messages, project settings, pinned memories, and (in the next phase) relevant artifacts, and turns them into LLM input.

---

## 2. DB Schema Changes

### 2.1 Existing tables (summary)

- `files`: stores uploaded/registered files and scope metadata.
- `artifacts`: stores extracted content and linkage to projects/conversations.
- `conversation_files`: links conversations to files.
- `project_files`: links projects to files.
- `conversation_artifacts`: links conversations to artifacts.

These are already present and used by the file upload + management code.

### 2.2 New `chunk_index` on `artifacts`

We add a positional index for multi-chunk artifacts per file:

- Column: `chunk_index INTEGER`

Semantics:

- `chunk_index` is zero-based.
- For a given `file_id`, all artifacts produced by one artifacting pass have `chunk_index = 0..N-1` without gaps.
- Single-chunk files can either store `chunk_index = 0` or `NULL`; we’ll prefer `0` for consistency.

Migration:

- Bump `SCHEMA_VERSION` to the next integer (currently 4 -> 5) in `db.py`.
- In the schema migration for `artifacts`, add:

  ALTER TABLE artifacts ADD COLUMN chunk_index INTEGER;

  using the existing `_add_column_if_missing` helper.

No existing data needs transformation; old artifacts will simply have `chunk_index = NULL` until re-artifacted.

---

## 3. Scoping Model for Artifacts

Artifacts are stored with both legacy and new scoping fields:

- `project_id` (legacy, non-null) – the physical container. All artifacts live under a project.
- `scope_type` – logical scope: "conversation", "project", "global" (future: "sandbox" or others).
- `scope_id` – integer scope identifier (e.g., `project_id` when `scope_type = "project"`).
- `scope_uuid` – UUID-like string identifier (e.g., `conversation_id` when `scope_type = "conversation"`).

Canonical meanings:

- Conversation-scoped artifact  
  - `scope_type = "conversation"`  
  - `scope_uuid = <conversation_id>`  
  - `project_id` = the project associated with that conversation, or a special project for unassigned chats.

- Project-scoped artifact  
  - `scope_type = "project"`  
  - `scope_id = <project_id>`  
  - `project_id = <same project_id>`  

- Global-scoped artifact  
  - `scope_type = "global"`  
  - `scope_id = NULL`, `scope_uuid = NULL`  
  - `project_id` may be a dedicated "Global" project row, or a reserved ID; we keep this flexible but consistent.

Retrieval helpers (future, for context builder):

- `list_artifacts_for_conversation(conversation_id, include_project=True, include_global=True)`:
  - Conversation scope: artifacts where `scope_type = "conversation"` and `scope_uuid = conversation_id`.
  - Project scope: artifacts where `scope_type = "project"` and `scope_id = conv.project_id` (if requested).
  - Global scope: artifacts where `scope_type = "global"` (if requested).
  - Only rows where `is_deleted` is false.
  - Ordered first by some priority (global -> project -> conversation, or reversed), then by `file_id`, then `chunk_index`.

- `list_artifacts_for_project(project_id, include_global=True)`:
  - Project-scope artifacts for the project.
  - Optionally global artifacts.

---

## 4. Artifactor Module

### 4.1 Location & API surface

New module: `server/artifacting.py` (name can be tweaked).

Primary entry points:

```python
def artifact_file(file_row: dict) -> list[str]:
    """Given a row from `files`, read the file, decide the handler, extract content,
    chunk it, and create artifacts. Returns a list of artifact IDs."""

def artifact_file_by_id(file_id: str) -> list[str]:
    """Convenience wrapper: fetch `file_row` by ID and call `artifact_file`."""
```

Helper used by both:

```python
def create_file_artifacts(
    *,
    project_id: int,
    file_id: str,
    scope_type: str,
    scope_id: int | None,
    scope_uuid: str | None,
    source_kind: str,
    provenance: str,
    chunks: list[str],
    base_name: str,
) -> list[str]:
    """Given pre-chunked text chunks, create a set of artifacts with chunk_index
    and return their IDs. Handles soft-deleting previous artifacts for this file."""
```

This helper will:

1. Look up existing artifacts for `file_id` (non-deleted).
2. Soft-delete them (`is_deleted = 1`, `deleted_at` set).
3. For each text chunk `chunks[i]`, call `create_scoped_artifact(...)` with:
   - `project_id`
   - `file_id`
   - `scope_type`, `scope_id`, `scope_uuid`
   - `source_kind` (e.g., "file:text", "file:pdf", "file:docx", "file:image", "file:zip")
   - `provenance` (e.g., "artifact:file_upload", "artifact:zip_child", etc.)
   - `chunk_index = i`
   - appropriate `name`, e.g. `"{base_name} (part {i+1})"` if more than one chunk.

### 4.2 File dispatching

`artifact_file(file_row)` will:

1. Inspect `file_row["path"]`, `file_row["mime_type"]`, and `name` extension.
2. Based on extension/MIME, select one handler:

   - `handle_zip(file_row)`
   - `handle_pdf(file_row)`
   - `handle_docx(file_row)`
   - `handle_image(file_row)`
   - `handle_text(file_row)`
   - `handle_code(file_row)` (optional distinction or folded into `handle_text`)

3. Each handler returns a list of artifact IDs (or for ZIP, can return a list of IDs across extracted children).

### 4.3 Error behavior

- Artifacting failures must not break the file upload endpoint.
  - On failure, log details (traceback when debug is enabled) and return an empty list of artifacts.
  - Optionally mark the file with `provenance` like "artifact:error:<message>" for debugging.

- Re-artifacting is safe because we always soft-delete previous artifacts for the same `file_id` before writing new ones.

---

## 5. File Type Behaviors

### 5.1 ZIP archives

Recognizer:
- Extension `.zip` or MIME `application/zip` (or similar).

Behavior:

- Treat the zip as a container:
  1. Create a subdirectory for extracted contents under the same scope path, e.g.:  
     `data/sources/projects/<project_id>/<zip_stem>_zip/`  
     or `data/sources/chats/<conversation_id>/<zip_stem>_zip/`.
  2. Iterate entries in the zip:
     - Skip entries with dangerous paths (`..`, absolute paths, or weird drive letters).
     - Limit extraction by:
       - max total extracted size (configurable),
       - max number of entries (configurable).
  3. For each extracted file:
     - Construct a new path inside the scope root.
     - `register_scoped_file` with the same logical scope as the parent zip:
       - `scope_type`, `scope_id`, `scope_uuid` copied from the zip’s `file_row`.
       - `source_kind = "upload:zip_child"`
       - `provenance = f"upload:zip:{parent_name}"`
     - Immediately call `artifact_file` on the child file.

- For the zip itself:
  - Optionally create a small "index" artifact summarizing the archive contents (e.g., list of filenames and sizes). This can be implemented as a separate, single-chunk artifact tied to the zip’s `file_id`.

### 5.2 PDF

Recognizer:
- Extension `.pdf` or MIME `application/pdf`.

Behavior:

- Attempt text extraction via a PDF library (e.g., `pypdf` or similar):
  1. Load the file from `file_row["path"]`.
  2. Extract text from each page, concatenating into one large string.
  3. If extraction yields essentially no text (e.g. scanned image-only PDF), either:
     - Skip artifacting for now (log and return), or
     - Create a single stub artifact indicating "PDF appears to contain no extractable text."

- For successful extraction:
  1. Feed the full text into the chunker (see Section 6).
  2. Use `create_file_artifacts` with `source_kind = "file:pdf"` and `provenance = "artifact:file_upload"`.

### 5.3 DOCX / Word

Recognizer:
- Extensions `.docx`, `.docm` (optionally `.doc` converted via a helper), or MIME like `application/vnd.openxmlformats-officedocument.wordprocessingml.document`.

Behavior:

- Use the existing word helper module from Callie Connector (ported into `server/word_helpers.py`):
  1. Open the file from `file_row["path"]`.
  2. Call a function like `extract_docx_markdown(...)` to produce a markdown-ish text representation:
     - Keeps headings, bold/italic markers.
     - Best-effort handling of tables and images.
  3. Feed the resulting markdown into the chunker.

- Create artifacts using:
  - `source_kind = "file:docx"`
  - `provenance = "artifact:file_upload"`

We can choose a conservative max text length per file to avoid pathological DOCX files (e.g., cut off at N characters with an "...[truncated]" notice).

### 5.4 Images

Recognizer:
- Extensions `.png`, `.jpg`, `.jpeg`, `.webp`, etc., or image MIME types.

Behavior:

- For now, artifacting images is a metadata bridge to the OpenAI image input format:
  - Create an artifact whose `content` is a small JSON blob or tagged text describing the image reference, for example:

    ```jsonc
    {
      "type": "image_reference",
      "file_id": "<file_id>",
      "path": "<absolute_or_relative_path>",
      "mime_type": "image/png"
    }
    ```

  - `source_kind = "file:image"`

- The context builder will later interpret these artifacts and:
  - Turn them into the proper OpenAI `input_image` objects (e.g. using the same logic as Callie Connector’s main.py currently does).
  - That translation is strictly an interim JSON -> OpenAI input step and not stored in the DB.

- Future extension: add a separate "image captioner" tool that takes an image file and produces a text caption artifact.

### 5.5 Plain Text: TXT, JSON, CSV, Markdown, source code

Recognizer:
- If MIME type starts with `text/`, or extension is clearly text-based (`.txt`, `.md`, `.json`, `.csv`, `.py`, `.js`, `.ts`, `.html`, `.css`, etc.).

Behavior:

- Use the existing byte-to-text helper from Callie Connector (`extract_text_bytes`) or equivalent:
  1. Read raw bytes from disk.
  2. Check for NUL bytes; treat as binary if found.
  3. Decode as UTF-8 with fallback (e.g., `errors="replace"`).
  4. Optionally strip excessively large files (with a truncation notice).

- For generic text files (including JSON/CSV):
  - Feed text into the chunker.
  - `source_kind = "file:text"` (or more specific e.g. "file:json", "file:csv" if you want).

### 5.6 Python and other source code

We can treat code as text, but with more careful chunking:

- Read via the same text helper.
- Chunk based on line boundaries, not raw characters:
  - Target chunk size: e.g., 200-400 lines or 3-6k characters.
  - When splitting:
    - Prefer boundaries at blank lines.
    - For Python, attempt to start chunks at lines starting with `def ` or `class ` to keep functions together when possible.
- Artifacts for code can use:
  - `source_kind = "file:code"`
  - `tags` (if used) like `["language:python"]` (optional).

The key is to avoid splitting in the middle of a function body where possible while still respecting size limits.

---

## 6. Chunking Strategy

We need a chunking strategy that is:

- Simple and fast.
- Reasonably token-aware.
- Stable enough that re-artifacting the same text produces the same chunk boundaries (unless config changes).

### 6.1 High-level rules

- Target chunk size: 3000-4000 characters per chunk (roughly 750-1000 tokens).
- Hard limit: 6000 characters per chunk (to avoid oversize artifacts).
- Minimum chunk size: 500 characters, unless the full file is smaller.

### 6.2 Splitting algorithm (text/markdown/JSON/etc.)

1. Normalize line endings to `\n`.
2. Split on double newlines (`\n\n`) to get “paragraph blocks”.
3. Start building chunks by appending blocks until adding another would exceed the target size.
4. If a single block itself exceeds the hard limit:
   - Split that block on single newlines.
   - Build sub-chunks up to the hard limit.
5. For each final chunk string, trim leading/trailing whitespace.

Result: a list of chunk strings suitable for `create_file_artifacts`.

### 6.3 Splitting algorithm (code)

1. Split on `\n` into lines.
2. Walk lines while accumulating into a chunk:
   - Keep track of current character count and line count.
   - Prefer to start chunks at:
     - `def ` or `class ` lines for Python.
     - Or top-level declarations in other languages (heuristics).
   - When current chunk would exceed the target line/char thresholds, start a new chunk.
3. Ensure each chunk ends on a line boundary.

This keeps code artifacts readable and preserves indentation integrity inside each chunk.

### 6.4 Ordering

For any artifact set produced from a file:

- Sort chunks in original order.
- Assign `chunk_index = i` in that order.
- Set `name` to either:
  - `file_row["name"]` if `len(chunks) == 1`, or
  - `f"{file_row['name']} (part {i+1})"` if multiple.

---

## 7. Triggers for Artifacting

### 7.1 On file upload

In `api_upload_file` (FastAPI endpoint):

- After each file is successfully written and registered via `register_scoped_file` and linked to the relevant conversation/project, call:

  ```python
  artifact_ids = artifact_file(file_row)
  ```

- For conversation scope:
  - Optionally link artifacts to the conversation via `conversation_link_artifact` (or similar helper).
  - Invalidate the conversation’s context cache.

- For project scope:
  - Artifacts are naturally associated via `project_id` and `scope_type = "project"`.
  - Invalidate the project’s context cache.

If artifacting throws, the upload still succeeds; the error is logged and can be retried via the manual API.

### 7.2 Explicit re-artifact endpoint

Add a dedicated endpoint:

```python
@app.post("/api/files/{file_id}/artifact")
def api_artifact_file(file_id: str):
    """Re-artifact this file."""
    artifact_ids = artifact_file_by_id(file_id)
    # Depending on scope, invalidate context caches for related conversations/projects.
    return JSONResponse({"artifacts": artifact_ids})
```

This is useful for:

- Files whose contents changed on disk (e.g., code pulled from git).
- Files that initially failed artifacting due to temporary errors.
- External callers like Callie Connector that want a “refresh” operation.

---

## 8. Context Integration (Future Phase)

This document mainly defines artifacting, but it needs to be compatible with the context builder.

### 8.1 Data flow into context builder

For a given chat:

1. Fetch conversation metadata and its `project_id` if any.
2. Collect:
   - Conversation messages.
   - Project system prompt / settings.
   - Pinned memories (global + project + conversation).
   - Artifacts via `list_artifacts_for_conversation(conversation_id, include_project=True, include_global=True)`.

3. Apply heuristics to select which artifacts to include:
   - Prefer artifacts tied directly to this conversation’s `file_id`s.
   - If context budget allows, include project-scope artifacts for the same project.
   - Include global artifacts only when explicitly requested or tagged as “high priority”.

4. Convert artifacts into OpenAI input segments:
   - Text artifacts => `{ "type": "input_text", "content": ... }` or plain strings.
   - Image reference artifacts (JSON) => `{ "type": "input_image", ... }` using the image translation logic reused from Callie Connector.

5. Assemble final prompt/context with proper ordering and truncation rules.

### 8.2 Caching

- Any time artifacting runs for a given file, the context cache should be invalidated for:
  - Conversations directly associated with that file.
  - Projects associated with that file’s scope.
- The cache entry key should include some versioning (e.g., a “context generation” or “last artifact update” timestamp) so that artifact changes cause cache invalidation.

---

## 9. Re-artifacting & Upsert Semantics

For a single file row (`file_id`):

- `artifact_file` will:
  1. Soft-delete existing artifacts where `file_id = ?`.
  2. Write a new set of artifacts with fresh `chunk_index` values.

This gives upsert semantics per `file_id`: the latest artifact set is the canonical one; older ones stay in the DB for forensics but are excluded from normal queries (`is_deleted` filter).

For duplicate uploads (same name, same scope):

- Current behavior: each upload is a new file row with a unique `id` and path (`foo.docx`, `foo_1.docx`, etc.).
- Artifacting applies independently per file row; there is no dedupe by name yet.
- The Manage Files UI can show multiple entries with the same name; the user can distinguish them via description or size/path.

Future enhancement (optional):

- Add `content_hash` and `size_bytes` to `files`.
- Decide logical “versioning” semantics based on `(scope_type, scope_id/uuid, name)` and hash.
- Either replace older versions automatically or let the user pick which file is canonical.

---

## 10. Future Extensions

Some planned or possible extensions that fit into this design:

1. Image Captioning Tool
   - Separate tool that reads image files and creates caption artifacts.
   - Could be invoked automatically after image upload or manually from the UI.

2. Structured JSON/CSV Summaries
   - For JSON/CSV files, add a second pass that:
     - Reads the structure.
     - Creates a short natural language artifact describing fields, counts, or schema.

3. Project-level Summarization
   - Periodically summarize artifacts in a project into a high-level “project knowledge” artifact for faster context building.

4. External Caller Support (Callie Connector)
   - Explicit API surface for external services:
     - `/api/files` – list files.
     - `/api/files/{file_id}/artifact` – trigger re-artifact.
     - `/api/files/{file_id}/artifacts` – list artifacts for a file.
   - Allows Callie Connector to lean on WyrmGPT’s Artifactor instead of duplicating file parsing logic.

---

## 11. Implementation Order

Suggested steps to implement this phase safely:

1. DB layer
   - Add `chunk_index` to `artifacts` via migration (`SCHEMA_VERSION` bump).
   - Implement helpers:
     - `list_artifacts_for_file(file_id, include_deleted=False)`
     - `soft_delete_artifacts_for_file(file_id)`
     - `create_scoped_artifact(...)` if not already in place.

2. Artifactor module
   - Create `artifacting.py` with `artifact_file` and `artifact_file_by_id`.
   - Implement handlers for:
     - Text/markdown/code.
     - DOCX (using `word_helpers`).
     - PDF (text only, best-effort).
     - ZIP (extract and recurse).
     - Images (metadata artifacts only, for now).

3. Wire to upload
   - Call `artifact_file(file_row)` in `api_upload_file`.
   - Invalidate context caches appropriately.

4. Manual re-artifact endpoint
   - Add `/api/files/{file_id}/artifact` and a button in the Manage Files UI.

5. Context builder integration (next phase)
   - Implement `list_artifacts_for_conversation` and use it in the context construction path.
   - Add heuristic selection and truncation.

This doc should be sufficient to re-implement or revisit the artifacting system later, even if the current chat or code context is lost.

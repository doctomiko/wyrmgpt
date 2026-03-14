# How WyrmGPT Works

Checked against the actual code in `WyrmGPT.20260313.d.zip` on March 13, 2026.

This is the “what is actually in the machine” version.

## The short version

WyrmGPT is a local-first chat application built from:

- a **FastAPI** backend
- a **vanilla JavaScript** frontend
- a local **SQLite** database
- local file storage under the app’s data directory
- optional **OpenAI embeddings** plus a local **Qdrant** vector store for semantic retrieval
- the **OpenAI Responses API** for model replies

It is not a browser-only toy. It has a real local storage layer, a real retrieval layer, and a real notion of scoped context.

---

## Main moving parts

### Frontend

The browser UI lives in `server/static/`.

The important files are:

- `index.html`
- `app.js`
- `styles.css`

The frontend is responsible for:

- showing conversations and projects
- sending chat requests
- opening the Personalization modal
- uploading files
- showing the context preview panel
- showing A/B results and letting the user choose the canonical answer

### Backend

The main backend entry point is `server/main.py`.

That file exposes routes for:

- chat
- A/B chat
- conversation management
- project management
- memory and pin management
- file upload and scope changes
- context preview
- corpus search
- app/query settings

### Database and storage

The main data layer is in `server/db.py`.

The app stores its structured state in SQLite and stores uploaded files on disk.

Large artifact bodies may spill into sidecar files rather than staying inline in SQLite.

### Context assembly

The brain of prompt assembly is `server/context.py`.

That is where WyrmGPT decides what belongs in the next model call.

### Retrieval

The retrieval logic lives mostly in:

- `server/query_retrieval.py`
- `server/db.py` for the actual index/search queries

### File extraction and artifacting

File extraction lives in:

- `server/artifactor.py`
- `server/word_helpers.py`
- `server/image_helpers.py`
- `server/zip_helpers.py`

---

## Core data model

WyrmGPT is built around several different record types.

### Conversations and messages

A conversation contains messages. Messages are the raw chat turns.

Each message stores:

- role
- content
- timestamps
- metadata
- optional author metadata

A/B assistant messages are stored too, along with metadata that marks which branch is canonical.

### Projects

Projects group conversations and files.

A project can also have:

- description
- system prompt
- visibility (`private` or `global`)
- override behavior for the core prompt
- default advanced mode flag

### Memory pins

Pins are the personalization/instruction layer.

They support:

- kind (`instruction`, `profile`, `style`, `preference`, etc.)
- title
- structured JSON value
- sort order
- enable/disable
- scope

The “About You” block is stored here as a special profile pin.

### Memories

Memories are separate from pins.

They are the retrievable long-term note system and include:

- content
- importance
- tags
- scope
- provenance fields

Each memory is also mirrored into an artifact so it becomes searchable like other corpus material.

### Files

Files are registered in the `files` table with:

- storage path
- MIME type
- scope
- provenance
- optional description
- SHA-256 hash
- soft-delete state

### Artifacts

Artifacts are normalized text-bearing records derived from files, memories, summaries, and transcripts.

The `artifacts` table holds things like:

- extracted file text
- conversation summary text
- conversation transcript text
- memory renderings
- metadata and hashes
- optional sidecar path for large content

### Corpus chunks

Artifacts are then split into chunks and written into `corpus_chunks`.

Those chunks are the main searchable retrieval substrate.

Each chunk tracks:

- artifact id
- source kind/source id
- optional file hints
- scope key
- chunk index
- chunk text

The full-text search index is `corpus_fts`.

### Embedding state

If vector retrieval is used, the app also tracks embedding state in `chunk_embedding_state`.

That lets it tell which chunks still need embeddings or have stale vectors.

---

## Scope model

WyrmGPT uses a real scope model.

A thing can be scoped to:

- a conversation
- a project
- global

That scope affects what can be included or retrieved.

### Project visibility

Projects can be marked `private` or `global`.

That matters especially for transcript retrieval across conversations.

A global project is allowed to leak outward by design. A private one is supposed to stay more self-contained, although the current code still has some rough edges around recent-chat retrieval.

---

## What happens when you send a message

This is the real flow.

### 1. The user message is saved

When you send a message, the backend stores the user turn in the conversation.

### 2. The app makes sure transcript artifacts are fresh enough

Before building context, `build_context()` tries to ensure the current conversation transcript artifact is reasonably up to date.

That means the app is continuously trying to keep the conversation searchable as a transcript artifact, not just as raw message rows.

### 3. Context sources are loaded

The app loads conversation and project context, including:

- project id
- project prompt
- project override setting
- personalization pins
- memories
- conversation summary
- visible files
- query settings

### 4. Personalization blocks are built

Pins are turned into readable system text blocks such as:

- ABOUT THE USER
- CUSTOM INSTRUCTIONS
- style/preferences sections

This becomes part of the effective system text.

### 5. Whole artifacts may be included

Depending on query settings, WyrmGPT may include whole artifacts directly, such as:

- pinned/scoped memory artifacts
- project conversation summaries
- file artifacts
- full chat transcript artifacts

This is one half of its retrieval strategy.

### 6. Search-based retrieval may run

If the current draft text is non-empty and the query settings allow it, WyrmGPT may run retrieval over the corpus.

The retrieval path can use:

- FTS only
- vector search only
- hybrid search that merges both

The retrieval code slices the user query, shapes an FTS query, runs searches, merges results, diversifies them, and builds debug information.

If the query settings allow expansion, some hits can be promoted from “matching chunk” into “include the whole artifact” or “include a local chat window.”

### 7. System text is assembled

The final system-side context stack is assembled from:

- core system prompt
- optional project prompt
- personalization blocks
- conversation summary
- retrieved RAG content block

### 8. Model input is assembled

`build_model_input()` then creates the actual message list sent to OpenAI.

That includes:

- one system message containing the assembled system text
- any whole-artifact/file messages
- prior conversation history
- the most recent user message

The app also injects a **zeitgeber** prefix into chat history messages so the model can see when they happened.

### 9. The model call is made

The backend calls the OpenAI Responses API.

Single chat uses `/api/chat`.

A/B mode uses `/api/chat_ab`, runs model A and model B in parallel, and stores both results.

### 10. Canonical branch handling matters later

In A/B mode, both answers are saved, but the user can mark one as canonical.

Later context building filters around that canonical choice so the chosen branch is what persists as the working history.

---

## How conversation summaries and transcripts work

These are separate and both matter.

### Conversation summaries

A conversation summary is stored as its own summary artifact.

That summary can be included directly in context and also reindexed into the corpus.

### Conversation transcripts

Every conversation can also have a transcript artifact.

The transcript renderer:

- formats message headers
- strips zeitgeber prefixes back out of the stored transcript body
- records message ids, times, and assistant/provider metadata
- marks transcript freshness in artifact metadata

On refresh, the app tries to append only what changed, but after that it still reindexes the artifact as a whole.

So the transcript system is useful and working, but not yet the final elegant version.

---

## How file artifacting works

When a file is uploaded or replaced:

1. the file is saved to the appropriate scope folder
2. a file row is registered or replaced
3. `artifact_file()` runs
4. `extract_text_from_file()` chooses an extraction strategy
5. the extracted text is written into an artifact
6. the artifact is reindexed into `corpus_chunks`

Extraction strategies currently include:

- image reference JSON for images
- ZIP entry listing for ZIPs
- `pypdf` text extraction for PDFs
- DOCX-to-markdown-ish extraction for Word files
- text decode fallback for plain text/code/config files

---

## Retrieval modes in real life

The retrieval layer is more mature than a toy FTS search, but less magical than the grand design docs imply.

### Full-text search

SQLite FTS is the grounded, working lexical search path.

It is chunk-based and scoped.

### Vector search

Vector search exists and is wired for:

- OpenAI embeddings
- local Qdrant backend

It is not provider-agnostic yet.

### Hybrid search

If both FTS and embeddings are enabled, the app merges them using reciprocal rank fusion.

### Retrieval debug and transparency

The retrieval code returns detailed debug information including:

- query slices
- shaped search queries
- raw result counts
- dominance by files/artifacts/chunks
- whether LLM query expansion would be recommended

The frontend context panel can display this because the preview path uses the same context assembly logic as the actual model input path.

That is a big design win: the preview is tied to the real payload rather than being a fake approximation.

---

## Configuration model

WyrmGPT reads settings from:

- `config.toml`
- `config.secrets.toml`
- environment variables as fallback

Config areas include:

- core prompt behavior
- OpenAI model defaults
- UI timing and timezone
- summary settings
- context limits
- retrieval behavior
- embedding provider/model
- vector backend
- app-level flags like `search_chat_history`

---

## What the app is especially good at right now

It is good at:

- keeping chat history local
- making project-scoped context possible
- showing its context pack before the model call
- artifacting text documents into searchable chunks
- storing and retrieving memories
- doing A/B model comparisons with canonical branch selection

The app is not pretending to be a mystery box. It actually exposes the context assembly machinery, which is the whole damn point.


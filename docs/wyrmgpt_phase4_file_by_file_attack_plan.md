# WyrmGPT Phase 4 File-by-File Attack Plan
_Last updated: Wednesday, March 11, 2026_

This plan is based on the **actual current tree** in `WyrmGPT.20260311.h.zip`.

## Files confirmed present

Relevant current files:

- `server/config.py`
- `server/main.py`
- `server/context.py`
- `server/db.py`
- `server/query_retrieval.py`
- `server/query_shaper.py`
- `server/query_slicer.py`
- `server/scripts/reindex_corpus.py`
- `server/static/app.js`

Also present and useful for new work:

- `server/scripts/`
- `docs/`
- `requirements.txt`

## Key findings from current code

1. `QueryConfig` in `server/config.py` is already mostly a retrieval-policy object.
2. `server/query_retrieval.py` already exists and is a natural place to evolve into hybrid retrieval orchestration.
3. `server/context.py` already has `do_vector_rag = has_user_text and ("EMBEDDING" in include_flags)` but currently only executes retrieval when `do_fts_rag` is true.
4. `server/db.py` already has a solid canonical corpus layer:
   - `corpus_chunks`
   - `corpus_fts`
   - artifact-to-corpus indexing
   - transcript artifact indexing
5. `server/main.py` already exposes query settings and UI config endpoints, so refactoring must preserve those.
6. `requirements.txt` does **not** yet include Qdrant or TOML tooling.

That means the best path is not a greenfield rewrite. It is a controlled rewire.

---

## Executive recommendation

Do the Phase 4 work in this order:

1. `server/config.py`
2. project-wide rename `QueryConfig` → `RetrievalConfig`
3. `server/query_retrieval.py`
4. add provider/vector adapter files
5. `server/context.py`
6. `server/db.py`
7. indexing scripts
8. `server/main.py`
9. `server/static/app.js`
10. `requirements.txt`

This order minimizes blast radius.

---

# 1. `server/config.py`

## What it is now

This file currently owns:

- `.env` loading via `dotenv`
- dataclasses for:
  - `CoreConfig`
  - `OpenAIConfig`
  - `UIConfig`
  - `SummaryConfig`
  - `ContextConfig`
  - `QueryConfig`
  - `AppConfig`
- environment-based config loader functions

## What to change first

### A. Rename `QueryConfig` → `RetrievalConfig`
Do a symbol rename first.

This is not just acceptable; it is the cleanest move because the class is already mostly retrieval policy.

### B. Keep `load_query_config()` temporarily
For the first pass, keep the function name if needed to avoid broad breakage, but have it return `RetrievalConfig`.

Then add a compatibility alias later if useful.

Example pattern:

```python
@dataclass(frozen=True)
class RetrievalConfig:
    ...
QueryConfig = RetrievalConfig  # temporary compatibility alias if needed
```

or just do the hard rename and fix imports globally.

### C. Add new config classes
Add:

- `ChatConfig`
- `EmbeddingConfig`
- `VectorConfig`
- `ImportConfig`

Keep:

- `CoreConfig`
- `UIConfig`
- `SummaryConfig`
- `ContextConfig`
- `OpenAIConfig`
- `AppConfig`

Recommended near-term provider-specific additions:

- `OllamaConfig`
- `SentenceTransformersConfig`

### D. Add TOML support
This file should become the canonical config loader.

Recommended behavior:

1. load `config.toml` if present
2. apply `.env` fallback or override during migration
3. build resolved dataclass objects

### E. Do not rip out `.env` immediately
Keep `.env` support during migration.

## What stays in `RetrievalConfig` for now

These are already retrieval policy or retrieval-adjacent:

- `query_include`
- `query_expand_results`
- `query_max_full_files`
- `query_max_full_memories`
- `query_max_full_chats`
- `query_expand_min_artifact_hits`
- `query_expand_chat_window_before`
- `query_expand_chat_window_after`
- `query_global_artifacts`
- `max_terms`
- `max_phrase_words`
- `max_phrase_chars`
- `filler_words_file`
- `filler_words`
- `long_query_chars`
- `max_query_slices`
- `retrieval_cache_ttl_sec`
- `retrieval_cache_max_entries`
- transcript inclusion flags and limits

## What should move out later

These are not really retrieval policy:

- `llm_expand_enabled`
- `llm_expand_prompt_file`
- `llm_expand_min_terms`
- `llm_expand_min_results`
- `llm_expand_max_keywords`
- `llm_expand_model`
- `llm_expand_max_tokens`

These can remain in `RetrievalConfig` in pass one, but should later migrate to either:

- `ChatConfig`
- or a smaller `QueryExpansionConfig` if you decide it deserves its own home

## Also add

Suggested new dataclasses:

```python
@dataclass(frozen=True)
class ChatConfig:
    provider: str = "openai"
    chat_model: str = "gpt-5.4"
    title_model: str = "gpt-5-mini"
    summary_model: str = "gpt-5-mini"
    query_expand_model: str = "gpt-5-mini"
    max_output_tokens: int = 4096
    stream: bool = True

@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "openai"
    model: str = "text-embedding-3-large"
    batch_size: int = 64
    normalize_vectors: bool = True
    cache_enabled: bool = True
    cache_dir: str = "./data/embedding_cache"
    reembed_on_text_hash_change: bool = True

@dataclass(frozen=True)
class VectorConfig:
    backend: str = "qdrant_local"
    collection_name: str = "wyrmgpt_chunks"
    local_path: str = "./data/qdrant"
    server_url: str = ""
    api_key: str = ""
    distance_metric: str = "cosine"
    upsert_batch_size: int = 256

@dataclass(frozen=True)
class ImportConfig:
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 200
    max_chunk_size_chars: int = 2000
    normalize_whitespace: bool = True
    strip_zeitgeber_from_stored_text: bool = True
    import_batch_size: int = 100
    embed_on_import: bool = True
    summarize_on_import: bool = False
    dedupe_by_text_hash: bool = True
```

---

# 2. Project-wide rename: `QueryConfig` → `RetrievalConfig`

## Why now
Because the current class already is retrieval policy in practice.

## What to touch
At minimum:

- `server/config.py`
- `server/context.py`
- `server/main.py`
- `server/query_retrieval.py`
- `server/db.py`

Potentially other import sites if present.

## Rule
Do the rename first and make the app boot again before carving fields out.

That gives you a stable midpoint.

---

# 3. `server/query_retrieval.py`

## What it is now

This is already the right seed crystal.

Current behavior:

- slices long user queries
- shapes FTS queries
- calls `search_corpus_for_conversation(...)`
- merges/dedupes FTS hits
- does simple diversification
- includes retrieval debug output
- has placeholder LLM-expansion logic

## What to do

This should become the main retrieval orchestration module.

### First pass changes

Keep the current FTS code path intact.

Add support for:

- FTS-only retrieval
- vector-only retrieval
- hybrid retrieval

Recommended additions:

```python
def retrieve_fts_chunks_for_message(...): ...
def retrieve_vector_chunks_for_message(...): ...
def retrieve_chunks_for_message(...):  # hybrid orchestrator
```

Or keep `retrieve_chunks_for_message(...)` as the public entry point and delegate internally.

### New shared hit structure

Normalize both FTS and vector results into the same internal shape:

```python
{
    "chunk_id": ...,
    "artifact_id": ...,
    "chunk_index": ...,
    "source_kind": ...,
    "source_id": ...,
    "file_id": ...,
    "filename": ...,
    "text": ...,
    "fts_score": ...,
    "vector_score": ...,
    "final_score": ...,
    "retrieval_channels": ["fts"] or ["vector"] or ["fts", "vector"],
}
```

### Move score fusion out of inline spaghetti
Either put helpers in this file or create:

- `server/retrieval/ranking.py`

Recommended helper functions:

- `rrf_fuse_hits(...)`
- `dedupe_retrieval_hits(...)`
- `apply_retrieval_boosts(...)`

### Use current cache carefully
The TTL cache currently keys on conversation/query/scoping flags. That is fine to keep for now, but it should later include retrieval mode and vector backend if vector results enter the mix.

## Why this file matters
Because it already exists, already owns retrieval debug, and already sits at the right seam between query shaping and corpus lookup.

Do not bypass it.

---

# 4. New provider adapter files

Create a new folder:

```text
server/providers/
```

Add:

- `server/providers/__init__.py`
- `server/providers/base.py`
- `server/providers/openai_embeddings.py`
- `server/providers/ollama_embeddings.py`
- `server/providers/sentence_transformers_embeddings.py`

## `server/providers/base.py`

Define the interface:

```python
from typing import Protocol

class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
```

## `server/providers/openai_embeddings.py`

This is the real initial implementation.

It should:

- read `EmbeddingConfig` + `OpenAIConfig`
- batch texts
- call OpenAI embeddings
- return plain vectors

No Qdrant logic.
No DB logic.
No context logic.

## Other provider files

For now, stub:

- `OllamaEmbeddingProvider`
- `SentenceTransformersEmbeddingProvider`

Even a clean `NotImplementedError` is enough in the first pass.

## Important rule
After this exists, raw OpenAI embedding calls should not appear elsewhere.

---

# 5. New vector adapter files

Create a new folder:

```text
server/vector/
```

Add:

- `server/vector/__init__.py`
- `server/vector/base.py`
- `server/vector/qdrant_local.py`
- `server/vector/qdrant_server.py`
- `server/vector/faiss_stub.py`

## `server/vector/base.py`

Define the interface:

```python
from typing import Protocol, TypedDict

class VectorRecord(TypedDict):
    chunk_id: int
    vector: list[float]
    payload: dict

class VectorHit(TypedDict):
    chunk_id: int
    score: float
    payload: dict

class VectorStore(Protocol):
    def ensure_collection(self, name: str, dimension: int) -> None: ...
    def upsert_chunks(self, items: list[VectorRecord]) -> None: ...
    def search(self, query_vector: list[float], *, top_k: int, filters: dict | None = None) -> list[VectorHit]: ...
    def delete_by_chunk_ids(self, chunk_ids: list[int]) -> None: ...
```

## `server/vector/qdrant_local.py`

This is the real vector backend for initial Phase 4.

It should:

- open local Qdrant storage path
- ensure collection exists
- upsert vectors with payload
- search vectors with optional scope filters
- delete vectors by chunk ID

## Payload recommendation
Store enough metadata for search-time scoping and later debugging:

- `chunk_id`
- `artifact_id`
- `scope_key`
- `source_kind`
- `source_id`
- `file_id`
- `conversation_id` if available
- `project_id` if available
- `filename`
- `chunk_index`
- `text_hash`

## `server/vector/qdrant_server.py`
Stub only for now.

Same interface, minimal placeholder.

## `server/vector/faiss_stub.py`
Stub only for now.

---

# 6. `server/context.py`

## What it is now

This file already:

- builds typed chat history
- gathers scoped files and memories
- determines query include flags
- sets:
  - `do_fts_rag`
  - `do_vector_rag`
- calls `retrieve_chunks_for_message(...)`
- formats retrieved chunks into the system block
- exposes retrieval diagnostics

## Critical current issue

Right now this block only runs when:

```python
if do_fts_rag:
    chunks_resp = retrieve_chunks_for_message(...)
```

That means `do_vector_rag` can be true while vector retrieval still does absolutely jack shit.

## What to change

### A. Replace `if do_fts_rag:` with retrieval-mode-aware logic
Recommended pattern:

```python
if do_fts_rag or do_vector_rag:
    chunks_resp = retrieve_chunks_for_message(
        conversation_id=conversation_id,
        user_message=user_text,
        limit=8,
        cfg=retrieval_cfg,
    )
```

Then let `query_retrieval.py` decide which channels actually run.

That is one of the most important concrete fixes in the whole Phase 4 pass.

### B. Keep the suppression/expansion logic here
This file already does good work suppressing:

- file-derived chunks when full files are already included
- chunks from fully included artifacts
- chunks from expanded artifacts

Leave that here for now.

It is context assembly behavior, not low-level retrieval behavior.

### C. Preserve current debug outputs
UI/debug already expects:

- `retrieved_chunks_raw`
- `retrieved_chunks_final`
- `retrieval_debug`

Keep those keys stable.

Just enrich them with vector provenance.

### D. Add vector-aware debug fields
When retrieval becomes hybrid, include in `retrieval_debug`:

- `retrieval_mode`
- `fts_active`
- `vector_active`
- `vector_backend`
- `embedding_provider`
- `candidate_counts`
- `channels_by_chunk`

That will save you from hallucinating about whether vector search is actually firing.

---

# 7. `server/db.py`

## What it is now

This is already the canonical corpus and application DB.

Important existing pieces:

- `corpus_chunks`
- `corpus_fts`
- FTS triggers
- artifact indexing helpers
- transcript artifact refresh/indexing
- `search_corpus_for_conversation(...)`
- scope logic for visible transcripts and artifacts

## What NOT to do

Do **not** put raw vectors into `corpus_chunks`.
Do **not** turn SQLite into a fake vector DB now that Qdrant local is chosen.

## What to add

### A. Text hash helper
You will want stable text freshness tracking.

Add something like:

```python
def compute_text_hash(text: str) -> str: ...
```

### B. Chunk lookup helpers for embedding/indexing
Add helpers such as:

- `get_corpus_chunk_by_id(chunk_id)`
- `list_corpus_chunks_missing_embeddings(...)`
- `list_corpus_chunks_requiring_reembed(...)`
- `list_corpus_chunks_for_artifact(artifact_id)`
- `get_corpus_chunks_by_ids(ids)`

### C. Optional local embedding state table
This is strongly recommended.

Add a small SQLite table such as:

```sql
CREATE TABLE IF NOT EXISTS chunk_embedding_state (
    chunk_id INTEGER PRIMARY KEY,
    text_hash TEXT NOT NULL,
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    last_embedded_at TEXT,
    status TEXT NOT NULL DEFAULT 'ready',
    FOREIGN KEY (chunk_id) REFERENCES corpus_chunks(id) ON DELETE CASCADE
);
```

This is **not** the vector store.
It is local bookkeeping so you know what has been embedded, with which model, and whether it is stale.

### D. Scope/payload helpers for vector indexing
Add helper(s) that assemble vector payloads from canonical rows.

For example:

```python
def build_vector_payload_for_chunk(chunk_row: dict) -> dict: ...
```

That keeps Qdrant payload generation out of the vector adapter.

## What stays as-is

- `search_corpus_for_conversation(...)` remains the FTS path
- existing transcript visibility logic remains useful
- existing corpus indexing remains canonical

---

# 8. New retrieval helper module(s)

You can do this inside `server/query_retrieval.py`, but I recommend adding:

- `server/retrieval/__init__.py`
- `server/retrieval/ranking.py`

## `server/retrieval/ranking.py`

Put score fusion here.

Recommended helpers:

- `rrf_fuse(...)`
- `merge_channel_hits(...)`
- `dedupe_hits(...)`
- `apply_boosts(...)`

## Why
The current codebase is just large enough that this logic will become soup if it lives inline in `query_retrieval.py`.

---

# 9. `server/main.py`

## What it is now

This file already has:

- app wiring
- request models
- config endpoints
- query settings endpoints
- chat endpoints
- summary handling
- lots of routing

## What to change

### A. Keep request/response surface stable where possible
You do not need to reinvent the front-end contract in the same pass as vector retrieval.

### B. Update imports after rename
Replace `QueryConfig` imports with `RetrievalConfig` as needed.

### C. Keep `/api/query_settings` endpoint initially
Even if the class is renamed internally, the API surface can stay named `query_settings` for now to avoid extra front-end churn.

You can rename that later if you want.

### D. Add eventual config endpoint(s) only if needed
Do not rush to expose the entire new TOML hierarchy through the API in the first pass.

### E. Dependency wiring
As the new adapters exist, `main.py` should eventually become the place where app services are built, not where business logic lives.

That can be incremental.

---

# 10. `server/static/app.js`

## What it is now

This file already:

- loads `/api/ui_config`
- loads `/api/app_config`
- loads `/api/query_settings`
- saves query settings
- renders context diagnostics

## What to change

### A. Keep current query settings UI stable
Checkboxes for:

- FILE
- MEMORY
- CHAT
- CHAT_SUMMARY
- FTS
- EMBEDDING

already exist.

That is good enough for initial vector rollout.

### B. Expose vector debug in context panel
If the context/debug panel already shows retrieval metadata, extend it to include:

- retrieval mode
- vector backend
- embedding provider
- candidate counts by channel
- whether a final chunk came from `fts`, `vector`, or `both`

### C. Avoid major UI redesign during Phase 4
The current UI already has the hooks needed to make vector retrieval inspectable.

Use them.

---

# 11. `server/scripts/reindex_corpus.py`

## What it is now

This already exists and likely handles corpus rebuild work.

## What to do
Review it and decide whether it should remain corpus-only or become part of a two-stage indexing process.

My recommendation:

- keep this script focused on rebuilding canonical `corpus_chunks`
- add a **new** script for embedding rebuilds

Do not conflate the two jobs.

---

# 12. New script: `server/scripts/rebuild_embeddings.py`

## This file should be added

This is one of the most important new files.

## What it should do

1. load config
2. open DB
3. create embedding provider
4. create vector store
5. fetch missing/stale chunks
6. embed in batches
7. upsert into Qdrant local
8. update local embedding-state bookkeeping
9. resume cleanly if interrupted

## Important rule
This script should work against already-imported canonical data.

It should not require chat requests to generate missing embeddings ad hoc.

---

# 13. New script: `server/scripts/check_embedding_freshness.py`

Optional but smart.

## What it should report
- total chunks
- chunks missing embeddings
- chunks stale by text hash
- counts by provider/model
- maybe a dry-run summary

This will help once the OpenAI export lands.

---

# 14. `requirements.txt`

## What it is now

Currently includes:

- `fastapi`
- `openai`
- `pydantic`
- `python-dotenv`
- etc.

## What to add

At minimum:

- `qdrant-client`

For TOML:
- if on Python 3.11+, `tomllib` is standard library
- if earlier Python, add:
  - `tomli`

If you later support local embeddings:
- `sentence-transformers`
- maybe `torch`

But do **not** add the heavy local stack in the first pass unless you are actually using it.

---

# 15. Concrete execution order

## Pass 1 — config + rename
Touch:
- `server/config.py`
- all `QueryConfig` import sites

Goal:
- app boots with `RetrievalConfig`
- `.env` still works
- TOML loader exists or is staged

## Pass 2 — retrieval abstraction
Touch:
- `server/query_retrieval.py`
- add:
  - `server/retrieval/ranking.py`
  - `server/providers/base.py`
  - `server/vector/base.py`

Goal:
- FTS path still works
- vector seam exists

## Pass 3 — real adapters
Add:
- `server/providers/openai_embeddings.py`
- `server/vector/qdrant_local.py`

Stub:
- `server/providers/ollama_embeddings.py`
- `server/providers/sentence_transformers_embeddings.py`
- `server/vector/qdrant_server.py`
- `server/vector/faiss_stub.py`

Goal:
- embeddings can be generated
- vectors can be stored/searched locally

## Pass 4 — DB bookkeeping
Touch:
- `server/db.py`

Goal:
- text-hash freshness helpers
- optional local embedding-state table
- chunk lookup helpers

## Pass 5 — hook into context
Touch:
- `server/context.py`

Goal:
- vector retrieval actually fires
- hybrid retrieval works
- current context-pack output shape remains stable

## Pass 6 — indexing scripts
Add:
- `server/scripts/rebuild_embeddings.py`
- optionally `server/scripts/check_embedding_freshness.py`

Goal:
- no inline brute-force misery
- large imports can be indexed sanely

## Pass 7 — UI/debug
Touch:
- `server/main.py`
- `server/static/app.js`

Goal:
- diagnostics show retrieval provenance
- user can tell whether hybrid retrieval is doing anything

---

# 16. Most important concrete fixes

These are the sharpest immediate wins.

## Fix 1
Rename `QueryConfig` to `RetrievalConfig`.

## Fix 2
Change `server/context.py` retrieval gate from:

```python
if do_fts_rag:
```

to effectively:

```python
if do_fts_rag or do_vector_rag:
```

and let retrieval orchestration decide which channels to run.

## Fix 3
Keep `server/query_retrieval.py` as the retrieval entry point instead of inventing a second parallel retrieval path.

## Fix 4
Add `qdrant-client` and isolate vector storage behind `server/vector/qdrant_local.py`.

## Fix 5
Add a real embedding rebuild script before the OpenAI export ingest becomes huge.

---

# 17. Anti-goals

Do not do these in the first Phase 4 pass:

- delete `.env` support immediately
- replace FTS
- rewrite the whole context builder
- shove vectors into SQLite
- implement FAISS first
- make Docker a requirement
- mix import success with embedding success
- explode the UI contract unless you absolutely have to

---

# 18. Final blunt take

The current build is actually in better shape for this than I expected.

Why?

Because:
- `QueryConfig` is already retrieval-oriented
- `query_retrieval.py` already exists
- `context.py` already acknowledges vector mode
- `db.py` already has a canonical corpus layer
- the UI already exposes retrieval settings

So the job is not “build vector RAG from scratch.”

The job is:

- rename the thing honestly
- add provider and vector seams
- make the vector path real
- keep the current FTS machinery alive
- avoid splattering OpenAI and Qdrant calls everywhere

That is very doable.

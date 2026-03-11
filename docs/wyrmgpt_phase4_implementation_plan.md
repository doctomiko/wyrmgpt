# WyrmGPT Phase 4 Implementation Plan
_Last updated: Wednesday, March 11, 2026_

This document assumes the following design decisions are already accepted:

- Keep existing FTS retrieval
- Add vector retrieval as a supplement, not a replacement
- Start with OpenAI embeddings, but behind an adapter
- Start with Qdrant local mode
- Treat Docker/server deployment as **Phase 4 vNext**
- Stub FAISS for later only
- Move from `.env` to `TOML`
- Treat current `QueryConfig` as the likely starting point for `RetrievalConfig`

---

## 1. Guiding strategy

The safest path is **controlled refactor, then feature integration**.

Do not try to:

- refactor config
- abstract providers
- add vector DB
- rewrite retrieval
- migrate imports

all in one giant holy-war commit.

Instead, do the work in layers:

1. Configuration foundation
2. Retrieval config rename / carve-out
3. Provider abstractions
4. Vector-store abstraction
5. Indexing pipeline
6. Hybrid retrieval
7. UI/debug transparency
8. Follow-on provider/server support

---

## 2. Proposed work breakdown

## Workstream A — Config refactor

### Goal
Move from `.env` to `TOML` and establish the new config object graph without breaking the current app.

### Deliverables
- `config.toml` support
- `config.py` refactor
- backward-compatible `.env` shim during migration
- new config classes:
  - `CoreConfig`
  - `ChatConfig`
  - `EmbeddingConfig`
  - `VectorConfig`
  - `RetrievalConfig`
  - `ImportConfig`
  - provider-specific configs

### Recommended approach
1. Add TOML loader first.
2. Keep current `.env` loading temporarily.
3. Build object mapping from loaded values into the new config classes.
4. Switch consumers one area at a time.
5. Remove direct `.env` assumptions only after parity is confirmed.

### Important rule
Do not make every call site parse raw config values. Centralize config resolution.

---

## Workstream B — Rename `QueryConfig` to `RetrievalConfig`

### Goal
Avoid unnecessary duplication if most of the current `QueryConfig` is already retrieval policy.

### Recommended approach
Use a symbol rename first, then carve off the pieces that are truly query-expansion or prompt-generation related.

### Suggested sequence
1. Rename `QueryConfig` → `RetrievalConfig`.
2. Run tests / startup checks / app boot.
3. Confirm behavior parity.
4. Identify fields that do **not** belong in retrieval policy.
5. Move only those fields into:
   - `ChatConfig`
   - a smaller query-expansion config later, if needed

### Why this works
This avoids inventing a second object that overlaps heavily with the first. It is lower-risk and cleaner.

### Likely keep in `RetrievalConfig`
- FTS/vector/hybrid mode
- top-k controls
- candidate counts
- merge strategy
- source priors
- significance/recency boosts
- filtering policy
- preview / context retrieval bounds

### Likely move out later
- LLM query expansion model choice
- prompt file paths for expansion
- any settings tied to text generation rather than retrieval policy

---

## Workstream C — Provider abstraction

### Goal
Stop OpenAI-specific logic from spreading further through the codebase.

### Deliverables
- `EmbeddingProvider` interface
- provider factory
- OpenAI embeddings adapter
- stubs or placeholders for:
  - Ollama embeddings
  - SentenceTransformers embeddings

### Suggested module layout

```text
server/
  providers/
    __init__.py
    base.py
    openai_embeddings.py
    ollama_embeddings.py
    sentence_transformers_embeddings.py
```

### Minimal interface

```python
class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
```

### Important rule
No raw OpenAI embedding SDK calls outside the OpenAI adapter.

---

## Workstream D — Vector-store abstraction

### Goal
Introduce a clean storage/search seam for vectors.

### Deliverables
- `VectorStore` interface
- Qdrant local adapter
- Qdrant server stub
- FAISS stub

### Suggested module layout

```text
server/
  vector/
    __init__.py
    base.py
    qdrant_local.py
    qdrant_server.py
    faiss_stub.py
```

### Minimal interface

```python
class VectorStore(Protocol):
    def ensure_collection(self, name: str, dimension: int) -> None: ...
    def upsert_chunks(self, items: list["VectorRecord"]) -> None: ...
    def search(self, query_vector: list[float], *, top_k: int, filters: dict | None = None) -> list["VectorHit"]: ...
    def delete_by_chunk_ids(self, chunk_ids: list[int]) -> None: ...
```

### Important rule
The rest of the app should not know whether vectors live in Qdrant local or Qdrant server.

---

## Workstream E — Vector indexing pipeline

### Goal
Create and maintain embeddings for corpus chunks without doing expensive ad hoc work at query time.

### Deliverables
- chunk text hash logic
- vector upsert path
- re-index script
- incremental embed/update logic

### Source of truth
`corpus_chunks` remains canonical text storage.

Vectors are derived artifacts.

### Recommended metadata stored with vector payload
- `chunk_id`
- `project_id` if applicable
- `conversation_id` if applicable
- `source_type`
- `created_at`
- `updated_at`
- `text_hash`
- optional significance or tags if helpful for filtering

### Important rule
Never embed decorated/zeitgeber-inflated prompt text. Embed the normalized stored chunk text.

### Suggested scripts
- `scripts/rebuild_embeddings.py`
- `scripts/check_embedding_freshness.py`

---

## Workstream F — Hybrid retrieval

### Goal
Merge vector retrieval into the existing RAG flow without breaking context assembly.

### Deliverables
- vector candidate search
- FTS + vector merge
- final top-k selection
- retrieval provenance

### Suggested retrieval flow
1. resolve retrieval scope
2. run FTS search if enabled
3. run vector search if enabled
4. fuse results
5. apply boosts
6. dedupe by `chunk_id`
7. format final context pack

### Initial merge strategy
Use **RRF** (Reciprocal Rank Fusion).

### Why RRF
It avoids premature score-calibration headaches.

### Suggested retrieval result structure
Each hit should be able to carry:
- `chunk_id`
- `source_channel` (`fts`, `vector`, or both)
- `fts_score`
- `vector_score`
- `final_score`
- metadata used for filtering/boosting

### Important rule
Keep the existing context-pack formatter if possible. Add the vector channel beside it, not by rewriting the whole assembly layer.

---

## Workstream G — UI and transparency

### Goal
Make vector retrieval visible and debuggable.

### Deliverables
- show retrieval channel
- show lexical / vector / final scores
- show why a chunk was selected
- optionally show candidate counts by source

### Minimum useful debug fields
- retrieval mode
- vector backend
- embedding provider
- candidate counts
- final chosen chunks
- channel(s) contributing to each chunk

### Why this matters
Without transparency, hybrid retrieval becomes “magic sludge” and debugging turns into séance work.

---

## Workstream H — Import pipeline alignment

### Goal
Ensure the planned large OpenAI export import path works with the new retrieval architecture.

### Deliverables
- `ImportConfig`
- import-time chunking
- import-time or deferred embedding
- dedupe by text hash
- resumable/restartable batch processing

### Recommended first behavior
- import chunks into canonical DB first
- generate embeddings in batches immediately after import, or in a resumable follow-up job

### Important rule
Do not tie import success to a single fragile embedding call. Imports should be restartable.

---

## 3. Recommended implementation order

## Step 1
Create TOML loader and new config classes.

## Step 2
Rename `QueryConfig` → `RetrievalConfig`.

## Step 3
Carve out clearly non-retrieval fields into `ChatConfig` or provider-specific config.

## Step 4
Add `EmbeddingProvider` interface and OpenAI adapter.

## Step 5
Add `VectorStore` interface and Qdrant local adapter.

## Step 6
Add vector indexing script and text-hash freshness tracking.

## Step 7
Add hybrid retrieval path using RRF.

## Step 8
Expose retrieval provenance in debug/meta UI.

## Step 9
Add stubs for:
- Qdrant server mode
- Ollama embeddings
- SentenceTransformers embeddings
- FAISS backend

---

## 4. File-level sketch

This is intentionally approximate, not prescriptive.

### Likely touched files
- `server/config.py`
- `server/main.py`
- `server/context.py`
- `server/db.py`

### Likely new files
- `server/providers/base.py`
- `server/providers/openai_embeddings.py`
- `server/providers/ollama_embeddings.py`
- `server/providers/sentence_transformers_embeddings.py`
- `server/vector/base.py`
- `server/vector/qdrant_local.py`
- `server/vector/qdrant_server.py`
- `server/vector/faiss_stub.py`
- `server/retrieval/hybrid.py`
- `server/retrieval/ranking.py`
- `scripts/rebuild_embeddings.py`

### Caution
Keep DB schema changes small and deliberate. Qdrant holds vectors; SQLite remains the canonical application database.

---

## 5. Suggested config matrix

```toml
[chat]
provider = "openai"

[embeddings]
provider = "openai"
model = "text-embedding-3-large"

[vector]
backend = "qdrant_local"

[retrieval]
mode = "hybrid"

[providers.openai]
api_key = "${OPENAI_API_KEY}"
```

Later **Phase 4 vNext** examples:

```toml
[embeddings]
provider = "ollama"
model = "embeddinggemma"

[vector]
backend = "qdrant_server"
server_url = "http://localhost:6333"
```

or:

```toml
[embeddings]
provider = "sentence_transformers"
model = "BAAI/bge-small-en-v1.5"
```

---

## 6. Acceptance criteria for initial completion

The initial implementation is “done enough” when:

1. app can load TOML config
2. `RetrievalConfig` exists in place of the old `QueryConfig`
3. OpenAI embeddings are called only through the adapter
4. Qdrant local can store and search vectors for corpus chunks
5. hybrid retrieval returns usable results
6. debug/meta UI can show which chunks came from FTS vs vector
7. import pipeline can index a large batch without collapsing into a pile of flaming raccoons

---

## 7. Anti-goals

Do not try to do these in the first pass:

- implement every provider
- add rerankers immediately
- perfect score calibration
- fully replace all old config code at once
- ship Docker as a hard dependency
- implement FAISS before Qdrant local works well

---

## 8. Final recommendation

Use the lowest-risk path:

- rename first
- carve second
- abstract providers
- add Qdrant local
- add hybrid retrieval
- improve deployment options later

This keeps momentum high without turning the project into refactor soup.

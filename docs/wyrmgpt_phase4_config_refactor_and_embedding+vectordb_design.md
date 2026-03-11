# WyrmGPT Config + Vector Retrieval Refactor
_Last updated: Wednesday, March 11, 2026_

## Naming correction

Use **Phase 4** for the initial vector-search integration work.

Use **Phase 4 vNext** for the follow-on work that expands provider options, Docker/server deployment paths, and additional vector-store backends.

Do **not** refer to that follow-on work as “Phase 5” in this design. That phase name is reserved for other roadmap work.

---

## Summary of decisions

We are keeping the current FTS-based RAG framework and **adding vector retrieval as a supplement**, not a replacement.

Initial implementation choices:

- **Embeddings provider:** OpenAI
- **Vector backend:** Qdrant local mode
- **Retrieval mode:** Hybrid (FTS + vector)
- **Config format:** Move from `.env` to `TOML`
- **Architecture direction:** Provider-agnostic adapters so OpenAI dependency is configuration-gated and can be replaced later

Planned future-facing support, but not required for initial integration:

- Ollama embeddings
- SentenceTransformers embeddings
- Qdrant server / Docker deployment mode
- FAISS stub backend

---

## Design goals

1. Keep the current code working with minimal disruption.
2. Avoid hard-wiring OpenAI into the long-term architecture.
3. Introduce vectors without replacing proven FTS retrieval.
4. Keep the end-user startup path simple.
5. Support larger local corpora, including imported OpenAI export history.
6. Prepare for later provider and backend swaps without rewriting the whole system.

---

## Why hybrid retrieval

FTS and vectors solve different problems.

FTS is good at:

- exact names
- literal phrases
- filenames
- code identifiers
- highly specific keyword matches

Vector retrieval is good at:

- semantic similarity
- paraphrases
- concept matching
- recovering relevant chunks when the wording changed

A hybrid system gives better recall without giving up precise lexical matches.

Recommended default:

- `retrieval.mode = "hybrid"`

Fallback modes should still exist:

- `fts`
- `vector`

---

## Configuration model

### Core config objects

The recommended top-level config objects are:

- `CoreConfig`
- `ChatConfig`
- `EmbeddingConfig`
- `VectorConfig`
- `RetrievalConfig`
- `ImportConfig`

Provider-specific config objects:

- `OpenAIConfig`
- `OllamaConfig`
- `SentenceTransformersConfig`

### Why `ChatConfig` instead of `ModelConfig`

“Model” becomes ambiguous once the app supports both chat models and embedding models.

`ChatConfig` is clearer and reduces future confusion.

### Why `RetrievalConfig` if `QueryConfig` already exists

`QueryConfig` already appears to handle much of the operational query behavior in the current build.

That means we should **not** rip it out immediately.

Instead:

- keep `QueryConfig` in place for current operational behavior
- introduce `RetrievalConfig` as the higher-level retrieval-policy layer
- adapt current code so `RetrievalConfig` feeds or wraps `QueryConfig`

This reduces refactor risk and avoids a wide code churn during the initial vector integration.

### Why `ImportConfig`

This config governs import / ingest behavior:

- transcript import
- OpenAI export import
- chunking
- dedupe
- embedding on import
- batch size
- normalization rules

`ImportConfig` is short, readable, and matches the actual work being done.

---

## Recommended config object responsibilities

## `CoreConfig`
Owns general runtime behavior.

Suggested fields:

- `app_env`
- `data_dir`
- `timezone`
- `debug_mode`
- `enable_rag`
- `enable_tools`
- `enable_memory`

## `ChatConfig`
Owns provider-agnostic chat behavior.

Suggested fields:

- `provider`
- `chat_model`
- `title_model`
- `summary_model`
- `query_expand_model`
- `temperature`
- `max_output_tokens`
- `stream`
- `timeout_seconds`
- `max_retries`

## `EmbeddingConfig`
Owns embedding generation behavior.

Suggested fields:

- `provider`
- `model`
- `dimensions`
- `batch_size`
- `normalize_vectors`
- `cache_enabled`
- `cache_dir`
- `reembed_on_text_hash_change`

## `VectorConfig`
Owns vector storage and vector search backend behavior.

Suggested fields:

- `backend`
- `collection_name`
- `distance_metric`
- `local_path`
- `server_url`
- `api_key`
- `prefer_grpc`
- `upsert_batch_size`

## `RetrievalConfig`
Owns retrieval policy.

Suggested fields:

- `mode`
- `fts_enabled`
- `vector_enabled`
- `top_k_final`
- `top_k_fts`
- `top_k_vector`
- `merge_strategy`
- `reranker_enabled`
- `filter_by_project`
- `filter_by_conversation`
- `recency_boost`
- `significance_boost`
- `source_prior_boost`
- `debug_explain_scores`

## `ImportConfig`
Owns import / ingest policy.

Suggested fields:

- `chunk_size_chars`
- `chunk_overlap_chars`
- `max_chunk_size_chars`
- `normalize_whitespace`
- `strip_zeitgeber_from_stored_text`
- `import_batch_size`
- `embed_on_import`
- `summarize_on_import`
- `dedupe_by_text_hash`

---

## Provider-specific configs

## `OpenAIConfig`

Suggested fields:

- `api_key`
- `base_url`
- `organization`
- `chat_model`
- `embedding_model`

## `OllamaConfig`

Suggested fields:

- `base_url`
- `chat_model`
- `embedding_model`
- `keep_alive`

## `SentenceTransformersConfig`

Suggested fields:

- `model_name`
- `device`
- `trust_remote_code`
- `normalize_embeddings`
- `batch_size`
- `cache_folder`

---

## Recommended TOML structure

```toml
[core]
app_env = "dev"
data_dir = "./data"
timezone = "America/New_York"
debug_mode = true
enable_rag = true
enable_tools = true
enable_memory = true

[chat]
provider = "openai"
chat_model = "gpt-5.4"
title_model = "gpt-5-mini"
summary_model = "gpt-5-mini"
query_expand_model = "gpt-5-mini"
stream = true
max_output_tokens = 4096

[embeddings]
provider = "openai"
model = "text-embedding-3-large"
batch_size = 64
normalize_vectors = true
cache_enabled = true
cache_dir = "./data/embedding_cache"
reembed_on_text_hash_change = true

[vector]
backend = "qdrant_local"
collection_name = "wyrmgpt_chunks"
local_path = "./data/qdrant"
distance_metric = "cosine"
upsert_batch_size = 256

[retrieval]
mode = "hybrid"
fts_enabled = true
vector_enabled = true
top_k_final = 12
top_k_fts = 30
top_k_vector = 30
merge_strategy = "rrf"
reranker_enabled = false
filter_by_project = true
filter_by_conversation = true
recency_boost = true
significance_boost = true
source_prior_boost = true
debug_explain_scores = true

[import]
chunk_size_chars = 1200
chunk_overlap_chars = 200
max_chunk_size_chars = 2000
normalize_whitespace = true
strip_zeitgeber_from_stored_text = true
import_batch_size = 100
embed_on_import = true
summarize_on_import = false
dedupe_by_text_hash = true

[providers.openai]
api_key = "${OPENAI_API_KEY}"
base_url = "https://api.openai.com/v1"

[providers.ollama]
base_url = "http://localhost:11434"
keep_alive = "5m"

[providers.sentence_transformers]
model_name = "BAAI/bge-small-en-v1.5"
device = "cpu"
normalize_embeddings = true
cache_folder = "./data/hf_cache"
```

---

## One-time `.env` to TOML conversion notes

The existing `.env` example can be converted, but some keys should be **re-homed** rather than copied mechanically.

Examples:

- `OPENAI_MODEL` → `[chat].chat_model`
- `OPENAI_TITLE_MODEL` → `[chat].title_model`
- `SUMMARY_MODEL` → `[chat].summary_model`
- `QUERY_LLM_EXPAND_MODEL` → `[chat].query_expand_model`
- `OPENAI_API_KEY` → `[providers.openai].api_key`
- `LOCAL_TIMEZONE` → `[core].timezone`
- `CONTEXT_*` → likely split between `[retrieval]`, `[chat]`, and legacy query/context settings
- `UI_*` → should remain in a UI-specific config section if still loaded into `app.js`

Recommended migration strategy:

1. Add TOML loader.
2. Keep `.env` support temporarily.
3. Map `.env` keys into the new object graph.
4. Move call sites over gradually.
5. Remove `.env` dependence after parity is achieved.

---

## Interface boundaries

To keep vendor and backend code from leaking all over the application, define these interfaces early.

### `EmbeddingProvider`

```python
class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
```

### `VectorStore`

```python
class VectorStore(Protocol):
    def ensure_collection(self, name: str, dimension: int) -> None: ...
    def upsert_chunks(self, items: list["VectorRecord"]) -> None: ...
    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        filters: dict | None = None,
    ) -> list["VectorHit"]: ...
    def delete_by_chunk_ids(self, chunk_ids: list[int]) -> None: ...
```

### `Retriever`

```python
class Retriever(Protocol):
    def retrieve(self, query: str, scope: "RetrievalScope") -> "RetrievalResult": ...
```

These interfaces let the rest of the app stay mostly ignorant of whether vectors came from OpenAI, Ollama, or SentenceTransformers, and whether they were stored in Qdrant local, Qdrant server, or something else later.

---

## Adapter layout recommendation

Suggested module layout:

```text
server/
  providers/
    __init__.py
    openai_chat.py
    openai_embeddings.py
    ollama_chat.py
    ollama_embeddings.py
    sentence_transformers_embeddings.py

  vector/
    __init__.py
    qdrant_local.py
    qdrant_server.py
    faiss_stub.py

  retrieval/
    __init__.py
    hybrid.py
    ranking.py
    filters.py
```

The goal is simple:

- app logic talks to interfaces
- adapters talk to SDKs or services
- vendor-specific behavior stays isolated

---

## Qdrant strategy

### Initial mode: `qdrant_local`

Start with Qdrant local mode to minimize moving parts.

Benefits:

- no Docker requirement for initial use
- no separate service process
- easy local persistence
- good fit for developer workflow on one machine

Recommended first implementation:

- `vector.backend = "qdrant_local"`

### Phase 4 vNext: `qdrant_server`

Add support for local or remote Qdrant server mode later.

Use cases:

- app runs on a local server instead of a desktop
- user wants Dockerized deployment
- larger corpus or better operational tooling is needed

Suggested later config:

- `vector.backend = "qdrant_server"`
- `vector.server_url = "http://localhost:6333"`

### Docker support

Support Docker as an **optional deployment path**, not an initial requirement.

This is especially important because some Windows users dislike or avoid Docker for practical reasons.

Potential UX later:

- a “deploy local Qdrant container” helper
- OS-specific start scripts
- Compose or bootstrap tooling

### FAISS

FAISS can exist as a stub backend in the design, but should not be implemented first.

Reason:

- Qdrant is a better fit for the near-term architecture
- FAISS would push more metadata, filtering, and persistence complexity into application code
- that complexity can be deferred unless there is a compelling future need

---

## Retrieval merge strategy

Recommended initial merge strategy: **RRF** (Reciprocal Rank Fusion)

Why:

- easy to implement
- robust across mixed scoring systems
- avoids over-optimizing score normalization too early

Suggested flow:

1. get FTS candidates
2. get vector candidates
3. fuse ranks with RRF
4. apply source/significance/recency adjustments
5. dedupe by chunk id
6. select final `top_k_final`

This is the right amount of sophistication for initial delivery.

---

## Initial implementation roadmap (Phase 4)

### Step 1 — Config refactor foundation
- add TOML loader
- add new config objects
- keep `.env` compatibility temporarily
- map existing keys into the new structure

### Step 2 — Provider abstraction
- define `EmbeddingProvider`
- define provider factory
- implement OpenAI embeddings adapter first
- leave Ollama / SentenceTransformers as planned follow-ons

### Step 3 — Vector abstraction
- define `VectorStore`
- implement Qdrant local adapter
- stub Qdrant server adapter
- stub FAISS adapter

### Step 4 — Vector schema and indexing
- add chunk-id keyed vector persistence model in Qdrant
- include metadata payloads needed for filtering
- add text-hash freshness logic
- add indexing / re-indexing script

### Step 5 — Hybrid retrieval
- add vector candidate retrieval path
- merge with FTS results
- keep current context-pack assembly shape

### Step 6 — Transparency/debug UI
- expose retrieval channel information
- expose lexical / vector / final scores
- show why each chunk made the cut

---

## Phase 4 vNext roadmap

### Provider expansion
- Ollama embeddings
- SentenceTransformers embeddings

### Deployment expansion
- Qdrant Docker/server mode
- launcher/bootstrap support

### Retrieval upgrades
- optional reranking
- richer metadata filters
- more advanced hybrid strategies if needed

### Backend expansion
- FAISS implementation only if the project later benefits from it

---

## Practical advice on refactor risk

Do not try to rewrite everything at once.

The lowest-risk path is:

- preserve existing query/context behavior
- add retrieval policy beside it
- add vector capability behind clean interfaces
- migrate incrementally

This is not the moment for a holy war about ideal architecture. This is the moment for controlled scaffolding that does not break the house while you are still living in it.

---

## Final recommendation

Proceed with:

- TOML-based structured config
- `ChatConfig`, `EmbeddingConfig`, `VectorConfig`, `RetrievalConfig`, `ImportConfig`
- OpenAI embeddings first, behind an adapter
- Qdrant local first
- hybrid retrieval
- Docker/server mode as Phase 4 vNext
- FAISS as a stub only for now

That gives the project a clean path forward without locking the system permanently to OpenAI or to one deployment style.

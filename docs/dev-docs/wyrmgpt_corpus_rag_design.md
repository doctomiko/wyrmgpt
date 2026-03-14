# WyrmGPT Corpus Retrieval (RAG) Design Doc

Doc/Vivian: this document is meant to be “switch-session proof.” It captures the architecture decisions, MVP scope, DB deltas, and growth limits for adding a RAG-style retrieval layer to the current WyrmGPT codebase.

## Goal

Add a **Corpus** subsystem that can retrieve and rank relevant context from multiple sources and feed it to the model before generation.

Target sources:
- Chat history (messages)
- In-scope documents and “memories” (artifacts, memories, files)
- Web search (ephemeral cache)

Non-goals for MVP:
- Perfect semantic search on day one
- Complex UI for bulk editing metadata (we’ll include a simple “inspect + edit one item” path)
- Production-grade crawler

## Why we need a Corpus table when we already have Artifacts

Artifacts are a great start, but they’re not the retrieval substrate we need:

1) **Artifacts are only one entity type.** RAG needs to retrieve from messages, memories, files, and web too. Adding retrieval fields to every table would smear the design and create 4–6 “almost the same” implementations.

2) **Retrieval is chunk-level, not object-level.** An artifact or file often needs 5–200 chunks. Messages might be 1 chunk each, but long ones may split. Chunk-level metadata (tags, significance, embedding id, extraction method) does not belong in the parent row.

3) **Ranking needs a unified scoring model.** We want one place to implement “BM25 + significance + recency + tag boosts + source priors,” not one per entity.

4) **Transparency requires stable provenance.** The user should be able to inspect *exactly which chunk* was retrieved and why. A Corpus row can carry provenance fields without polluting core tables.

Artifacts remain valuable: they’re “authoritative edited content.” The Corpus simply **indexes** artifacts (and everything else) into retrievable chunks.

## Key idea

Create a **CorpusChunk** entity: one row = one retrievable chunk, regardless of source.

Every source object (message, memory, artifact, file chunk, web page) can produce 1..N Corpus chunks.

## Naming: “Corpus”

“Corpus” is a standard term in linguistics / IR / ML literature (corpus of documents). It is widely used and not specific to any one AI company. (This is not legal advice, but it’s about as generic as “dataset” or “index.”)

## Existing schema context (from current codebase)

Current tables relevant to retrieval:
- `conversations (id TEXT PK, project_id, title, summary_json, ...)`
- `messages (id INTEGER PK, conversation_id TEXT, role, content TEXT, created_at TEXT, meta TEXT)`
- `memories (id TEXT PK, content TEXT, importance INTEGER, tags TEXT, ...)`
- `artifacts (id TEXT PK, project_id INTEGER, name TEXT, content TEXT, tags TEXT, ...)`
- `files (id TEXT PK, name, path, mime_type, ...)`
- project linking tables exist (`project_files`, `project_conversations`, etc.)

There is not yet a unified chunk table for all entities; artifacts currently store their full content in one row.

## Architecture overview

Pipeline per request (MVP):
1) Build a retrieval query from user prompt (and optionally conversation/project scope)
2) Retrieve candidates from:
   - Corpus (chat + artifacts + memories + file extracts)
   - Web (optional, cached)
3) Rank candidates
4) Assemble a **Context Pack**: top chunks + short provenance lines
5) Send to model along with the user message
6) Provide transparency:
   - A “context panel” showing the exact chunks included and their sources

### Ranking model (MVP)

Use SQLite **FTS5** for fast lexical retrieval and relevance scoring (BM25). Then apply cheap boosts:
- significance boost (your “fluff vs canon”)
- tag boost (exact tag matches)
- source priors (memories/artifacts > random assistant chatter, unless query says otherwise)
- recency boost for chat history

Later (post-MVP): add embeddings + vector search + LLM reranker. But FTS5 is the fastest 1–2 day win.

## Proposed database changes

### 1) Corpus chunks table

```sql
CREATE TABLE IF NOT EXISTS corpus_chunks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,

  -- What is this chunk derived from?
  source_type   TEXT NOT NULL,          -- 'message' | 'memory' | 'artifact' | 'file' | 'web'
  source_id     INTEGER,                -- for int-keyed sources (e.g., messages.id)
  source_uuid   TEXT,                   -- for uuid/text-keyed sources (e.g., artifacts.id, files.id, memories.id)
  source_key    TEXT NOT NULL,          -- canonical: e.g. "message#:123" or "artifact:uuid"

  -- Chunk identity within the source
  chunk_index   INTEGER NOT NULL DEFAULT 0,

  -- Text and metadata
  title         TEXT,                   -- optional (artifact name, filename, page title)
  text          TEXT NOT NULL,          -- the chunk content
  tags_json     TEXT,                   -- JSON array of tags/terms
  significance  REAL NOT NULL DEFAULT 0.2,  -- 0..1 (or 0..100 if you prefer)
  meta_json     TEXT,                   -- provenance: extraction, model, scope, etc.

  -- Scoping
  project_id    INTEGER,                -- if known; helps limit retrieval to a project
  conversation_id TEXT,                 -- if derived from a message; helps conversation-scoped retrieval

  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_corpus_source_key ON corpus_chunks(source_key);
CREATE INDEX IF NOT EXISTS idx_corpus_project ON corpus_chunks(project_id);
CREATE INDEX IF NOT EXISTS idx_corpus_conversation ON corpus_chunks(conversation_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_corpus_source_chunk ON corpus_chunks(source_key, chunk_index);
```

#### Source key rules

- If `source_uuid` exists: `source_key = f"{source_type}:{source_uuid}"`
- Else: `source_key = f"{source_type}#:{source_id}"`

This avoids ambiguity when some tables are keyed by int and others by text UUID.

### 2) Full-text search virtual table (FTS5)

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS corpus_fts
USING fts5(
  text,
  title,
  tags,
  content='corpus_chunks',
  content_rowid='id'
);
```

Triggers to keep it in sync (MVP quality, standard pattern):

```sql
CREATE TRIGGER IF NOT EXISTS corpus_ai AFTER INSERT ON corpus_chunks BEGIN
  INSERT INTO corpus_fts(rowid, text, title, tags) VALUES (new.id, new.text, new.title, new.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS corpus_ad AFTER DELETE ON corpus_chunks BEGIN
  INSERT INTO corpus_fts(corpus_fts, rowid, text, title, tags) VALUES('delete', old.id, old.text, old.title, old.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS corpus_au AFTER UPDATE ON corpus_chunks BEGIN
  INSERT INTO corpus_fts(corpus_fts, rowid, text, title, tags) VALUES('delete', old.id, old.text, old.title, old.tags_json);
  INSERT INTO corpus_fts(rowid, text, title, tags) VALUES (new.id, new.text, new.title, new.tags_json);
END;
```

(We can later store tags as a flattened string field for FTS; MVP can reuse tags_json but may want a `tags_flat` column.)

### 3) Minimal metadata extension options (optional)

You already have `memories.importance` and `artifacts.tags`. MVP can map those into corpus fields at ingestion time without changing the original tables.

If you want *native* significance on all entity types later, add it to the Corpus only. No need to touch messages/memories/artifacts/files.

## MVP scope (doable in 1–2 days)

### Day 1: Corpus ingestion + FTS search

1) Add the new tables (`corpus_chunks`, `corpus_fts` + triggers)
2) Add an ingestion function in `artifactor.py` (or a new `corpus.py`) to upsert corpus chunks from:
   - Messages (user + assistant), 1 chunk per message (MVP)
   - Memories, 1 chunk each
   - Artifacts, chunked (you already have chunking artifacts; reuse it)
   - Files: MVP can be “text-only” files first; PDFs later
3) Add a `/api/corpus/search` endpoint:
   - inputs: query, project_id?, conversation_id?, limit, source_type filter?
   - returns: ranked chunks with bm25 score + boosts + provenance
4) Add a “context panel” view that shows retrieved chunks and their sources (even if plain JSON at first)

### Day 2: Request-time retrieval + web stub

5) Add “pre-response retrieval” to the chat endpoint(s):
   - For each user prompt, retrieve top K corpus chunks and attach them as a context pack
   - Add transparency fields in response: list of chunk ids used
6) Add **web search** as a separate step:
   - call web search
   - store results as source_type='web' in corpus_chunks with a TTL field in meta_json
   - include top N in the context pack
7) Add minimal “edit metadata” endpoint (MVP):
   - update tags_json + significance for a corpus chunk
   - allows user transparency + manual curation

MVP deliberately uses **FTS5** first because it’s:
- fast to implement
- explainable
- good enough for most “find the thing we said / find the doc section” needs

Embeddings and reranking can be added after MVP.

## Retrieval and ranking details (MVP)

### Candidate retrieval

Query FTS:

```sql
SELECT c.id, c.source_type, c.source_key, c.title, c.text, c.tags_json, c.significance,
       bm25(corpus_fts) AS bm25_score
FROM corpus_fts
JOIN corpus_chunks c ON c.id = corpus_fts.rowid
WHERE corpus_fts MATCH ?
  AND (? IS NULL OR c.project_id = ?)
  AND (? IS NULL OR c.conversation_id = ?)
ORDER BY bm25_score
LIMIT ?;
```

Then in Python apply boosts:
- significance_boost = `1.0 + (significance * w_sig)`
- tag_boost if query overlaps tags
- recency_boost for chat messages (optional quick: based on created_at)
- source_prior boost (memories/artifacts > messages)

Final score example:
`final = (-bm25_score) * significance_boost * source_prior * recency_boost`

(FTS5 bm25 is “lower is better” by default; we can invert or normalize.)

### Context pack format (transparent and stable)

The model should receive a pack like:

```
[Context Pack]
(1) source=artifact:XYZ name="DB Migration Notes" chunk=3 score=...
<chunk text>
(2) source=message#:1234 role=user at=... score=...
<chunk text>
...
```

But keep it short. The pack is not for the user; it’s for the model. The UI should show provenance and allow inspection.

## Zeitgeber interaction

Your zeitgeber prefixes are for **model temporal reasoning**. They should not be stored in DB content and should be stripped from UI.

In the Corpus ingestion layer:
- ingest from the **stored DB content** (already stripped), not from the model input
- store created_at separately in corpus_chunks and optionally expose a UI “timestamp” column

For model input:
- you can add zeitgeber to the context pack too, but do not store it.

## Upper limits and sizing guidance (practical)

SQLite can handle a lot. The real constraints are:
- disk size
- query latency
- embedding storage (if/when you add it)

### Back-of-envelope capacity

Assume:
- 100 chats/day (heavy usage) * 365 = 36,500 messages/year
- Average message chunk stored in corpus: 600 characters (~120–150 tokens)
- corpus_chunks row overhead + indexes: roughly 1–2 KB per chunk (very rough)

Then:
- 36,500 chunks/year ≈ ~50–100 MB/year for text + indexes
- 5 years: ~250–500 MB for chat-only corpus

Artifacts and files can dominate. If you index a lot of PDFs or large repos, it can grow faster.

FTS5 with ~100k–500k rows is still perfectly workable on a desktop-class machine if you keep queries scoped (project_id, conversation_id) and limit K.

### Embeddings (post-MVP) are the real bloat

If you store 1536-float embeddings:
- 1536 floats * 4 bytes ≈ 6 KB per chunk (raw float32)
- 100k chunks → ~600 MB just for vectors

Recommendation:
- store embeddings in a separate table (or a separate vector store) later
- do not add embeddings to MVP unless required

### Practical “upper bounds” for MVP design

MVP target:
- 0–200k corpus chunks
- single SQLite file < 1–2 GB
- typical query: < 200 ms with scope filtering

When you outgrow that:
- move embeddings to a vector DB (FAISS, Qdrant, etc.)
- keep SQLite as the authoritative metadata store

## Why this stays robust

- One retrieval substrate for all entities
- Chunk-based design avoids reworking artifacts or messages schema
- Metadata can be extended later without schema churn across 5 tables
- FTS5 provides immediate value; embeddings can be added without redesign

## Open questions (deferred, not blocking MVP)

- How to scope web results by project vs global
- How aggressive chunking should be per source type
- Whether to auto-summarize long chunks for the model context pack
- How to expose batch retrofit UI (likely a background job)

## MVP checklist (literal)

Day 1:
- [ ] Add corpus_chunks + corpus_fts + triggers
- [ ] Build ingestion for messages/memories/artifacts (files optional)
- [ ] Add `/api/corpus/search`
- [ ] Basic UI: show retrieved chunks and their provenance

Day 2:
- [ ] Integrate retrieval into `/api/chat` and `/api/chat_ab` pre-response
- [ ] Add web retrieval cache as source_type='web'
- [ ] Add “edit corpus metadata” endpoint (tags/significance)
- [ ] Add “retrofit” script to backfill corpus from existing DB

---

If you want this document to double as an implementation plan, the next step is to add “exact function names and call sites” in `artifactor.py`, `context.py`, and `main.py`, but I’ve kept that out of this version so it stays readable and design-first.

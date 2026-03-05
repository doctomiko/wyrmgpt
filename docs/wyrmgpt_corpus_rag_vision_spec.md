# WyrmGPT Corpus RAG Vision & Spec (Project Guide)

This is a **vision document + functional spec** for adding retrieval‑augmented generation (RAG) to WyrmGPT, with a strong emphasis on **transparency**, **user agency**, and **future-proofing**. It’s written to survive chat/session switches and to guide implementation decisions.

---

## 1. The mission

WyrmGPT is evolving from “a chat UI for models” into a **context instrument**: a system that can reliably answer questions using your *actual* material (chats, memories, artifacts, files, web), with clear visibility into **what it used** and **why**.

RAG is how we keep answers grounded:
- Reduce hallucination by grounding in retrieved text
- Make answers reflect your canon (projects, decisions, lore, code, writing)
- Keep the system current (web and new docs) without retraining

---

## 2. What “good” looks like

When the user asks something, WyrmGPT should be able to:
1) **Search** relevant sources (history, documents, web)
2) **Rank** what it found (and explain ranking at least at a high level)
3) **Assemble a context pack** (what gets sent to the model)
4) **Answer** using that pack (grounded)
5) **Show its work** (transparency panel: chunks used, provenance, scores, why included)
6) **Let the user correct the world** (tags/significance edits; promote/demote results; retrofits)

The user should never have to “trust vibes.” If the system used a chunk, it should show it.

---

## 3. The sources we want

### 3.1 Chat history (messages)
Purpose: remember what was said, decisions made, details agreed upon, debugging steps, etc.

Key needs:
- Conversation scoping (this chat vs project vs global)
- Recency weighting
- Ability to answer “what did we decide last time?” reliably

### 3.2 In-scope documents / memories
These are your “authoritative” sources:
- artifacts (curated documents, chunks you already have)
- memories (canonical facts + important summaries)
- files (uploaded text, extracted docs)

Purpose: answer based on the **real canon**, not whatever the model guesses.

Key needs:
- Chunking
- Metadata (tags, significance, provenance)
- Strong source priors (memories/artifacts often outrank random chat)

### 3.3 Web search (ephemeral)
Purpose: fill in “now” when you need current facts, especially outside your internal corpus.

Key needs:
- Recency and source quality
- Clear labeling as external + time-stamped
- Caching with TTL so it doesn’t bloat your canon unless promoted

---

## 4. Why a unified Corpus layer is necessary

You already have an `artifacts` table and chunk artifacts. That’s not enough for a real retrieval system because:

1) **Retrieval is chunk-first.** Artifacts are one entity type; RAG wants chunks from many types (messages/memories/files/web).  
2) **Metadata should not be smeared across core tables.** If you bolt tags/significance/embedding fields onto messages + memories + artifacts + files, you will change schema in 4 places forever.  
3) **Ranking should be centralized.** One ranking pipeline should handle all sources, not one per table.  
4) **Transparency requires stable IDs for chunks.** A unified corpus chunk id is the “receipt” you show users.

So: artifacts remain a source of content; the **Corpus** is the **retrieval substrate**.

---

## 5. Core concept: Corpus Chunks

A **CorpusChunk** is “a retrievable unit of text + metadata,” regardless of origin.

Each chunk has:
- where it came from (source_type + source_id/source_uuid)
- the text (chunk)
- metadata (tags, significance, provenance)
- scoping info (project_id, conversation_id, etc.)
- optional search indexes (FTS entry now; embeddings later)

This gives you a single place to add fields later without schema churn.

**Important design constraint:** Your system has both int IDs and UUID/text IDs. Corpus must support both: `source_id` and `source_uuid`, plus a canonical `source_key`.

---

## 6. Metadata: what and why

You explicitly want:
- **tag terms** (keywords, concepts, names)
- **overall significance** (fluff vs canonical / important)

This is the *right instinct*. Good metadata makes retrieval sane and makes ranking explainable.

### 6.1 Tags
Purpose:
- Query routing (“this is a code question”, “this is lore”, “this is politics/news”)
- Boosting relevant chunks (“show me anything tagged ‘migration’ or ‘zeitgeber’”)
- User edits: tags become the “manual override knobs”

Implementation notes:
- Store tags as JSON array for flexibility, but also store a flattened string for FTS boosting if needed.
- Allow tags at both chunk-level and source-level later; MVP just chunk-level.

### 6.2 Significance
Purpose:
- Canon > chatter
- “This matters” should win against random matches
- Lets the user curate what the system remembers

Define it as 0..1 or 0..100. The doc uses 0..1. Either is fine; 0..1 is nicer in scoring.

Where it comes from:
- initial default per source_type (artifacts/memories start higher)
- optional automated suggestion pass (not required for MVP)
- user edits override everything

### 6.3 Provenance / audit trail
Purpose:
- Transparency: explain how a chunk was created
- Debugging: know whether a chunk came from OCR, summarization, user edits, etc.

Store as `meta_json`:
- extraction method
- chunking parameters
- created_by (user/system)
- TTL for web entries, etc.

---

## 7. Retrieval pipeline (end-to-end)

### 7.1 Inputs
- user query text
- current conversation_id
- current project_id (if applicable)
- user search intent (explicit command or inferred mode)
- user filters (optional: “only search artifacts”)

### 7.2 Step A — Candidate generation (fast)
MVP uses **SQLite FTS5**:
- fast
- explainable
- easy to scope

Candidates come from:
- corpus chunks matching query (BM25)
- optional quick tag matches

### 7.3 Step B — Scoring / boosting (cheap)
On top of BM25:
- significance boost
- source prior (memories/artifacts > chat)
- recency boost for messages (especially in active thread)
- tag overlap boost

This is where “ranking differs per query type” lives. Examples:
- “What did we decide last time?” => boost conversation_id + recent messages + high significance
- “Where in the docs is X?” => boost artifacts/files + tags
- “What’s the latest news?” => web-first mode with strong recency constraints

### 7.4 Step C — Optional reranking (post-MVP)
Later you add:
- embeddings (semantic similarity)
- reranker model to pick best top 10–20 chunks

Not required for MVP.

### 7.5 Step D — Context pack assembly
Take top chunks, then:
- deduplicate near-duplicates
- enforce diversity across sources if helpful
- include concise provenance lines

### 7.6 Step E — Model call
Send:
- system instructions
- context pack
- user message

### 7.7 Step F — Transparency output
Return (or expose in UI):
- list of chunk IDs used
- why they were included (scores + boosts)
- source links (to message/artifact/file)

---

## 8. Zeitgeber and time: how it fits

You already built zeitgeber prefixes to help the model reason about “when.” That’s separate from the Corpus.

Rules:
- Zeitgeber is **model-visible**, not user-visible.
- Zeitgeber should **never** be stored in message content or corpus text.
- If you want time reasoning inside corpus context packs, include time as metadata lines, not inline in chunk text.

For model comprehension, prefer:
- `⟂t=YYYYMMDDTHHMMSSZ ⟂age=N` (UTC + rolling age seconds computed at request build time)

For corpus transparency, show:
- the stored created_at field as user-friendly time (in configured UI timezone)

---

## 9. Web search as a first-class source

Treat web results as:
- `source_type='web'`
- cached corpus chunks with TTL metadata
- clearly labeled as external and time-stamped

MVP approach:
- when user enables web search (or query requires it), fetch results
- extract text
- chunk + insert into corpus with TTL
- rank alongside internal corpus (or separately then merge)

Promotion path:
- user can “Promote to Artifact” or “Save as Memory” if a web fact becomes canon

---

## 10. UX and transparency requirements

Transparency is not optional; it’s a core product feature.

### 10.1 Context panel must show model truth
The context window should display **exactly what is sent to the model** (including retrieval pack. This includes any zeitgeber tags.

### 10.2 User inspectability
User can click a retrieved chunk and see:
- source type and link to original (message, artifact, file, web)
- chunk text
- tags
- significance
- ranking info (at least “BM25 + boosts”)
- provenance meta_json

### 10.3 User editability (MVP minimal)
User can:
- edit tags
- edit significance
- optionally “exclude this chunk from retrieval” (a future boolean)

This is how the system gets better over time.

### 10.4 Retrofit / batch jobs
A “retrofit” job should:
- backfill corpus chunks for existing messages/artifacts/memories
- optionally propose tags/significance
- allow review

MVP can be a CLI script.

---

## 11. MVP: 1–2 days, realistic

The MVP is deliberately designed to be valuable without embeddings.

### MVP deliverables
1) Corpus tables + FTS5
2) Ingestion/upsert for:
   - messages (1 chunk each)
   - artifacts (chunked)
   - memories (1 chunk each)
   - files (text-only subset)
3) Search endpoint: `/api/corpus/search`
4) “Context pack” assembly + injection into `/api/chat` and `/api/chat_ab`
5) Transparency:
   - UI panel shows the exact context pack chunks with provenance
6) Metadata editing endpoint:
   - update tags + significance for a chunk

### What we explicitly defer
- Embeddings / vector DB
- LLM reranker
- PDF OCR pipeline
- Full batch-edit UI

---

## 12. Database changes (summary)

Database details are in the companion DB design, but the important spec-level fact is:

- Add `corpus_chunks` (unified chunk table)
- Add `corpus_fts` (FTS5 virtual table) + triggers
- Support both `source_id` and `source_uuid`
- Use `source_key` + `chunk_index` for uniqueness

This design prevents schema sprawl across messages/memories/artifacts/files.

---

## 13. Size and growth expectations (upper limits)

### 13.1 Chat volume
Even heavy use is manageable.

Example:
- 100 messages/day => ~36,500/year
- 5 years => ~182,500 message chunks

FTS5 can handle ~100k–500k rows fine on a desktop-class machine if you scope queries.

### 13.2 Corpus chunk growth
Artifacts/files can dominate size:
- indexing a large codebase or multiple PDFs can create tens of thousands of chunks quickly

MVP mitigation:
- scope retrieval by project_id
- limit chunk sizes and keep chunk counts reasonable
- add a cap per source to avoid runaway ingestion

### 13.3 Embeddings are the real bloat (post-MVP)
Vectors can dwarf text storage. Keep embeddings out of MVP and add later as a separate store.

---

## 14. Risks and how we handle them

### Risk: Two versions of truth
Mitigation: context panel must use the same function/data structure as the model call.

### Risk: Retrieval returns junk
Mitigation: significance + tags + user edits + source priors.

### Risk: Web results pollute canon
Mitigation: TTL + explicit promotion workflow.

### Risk: Chunking choices become legacy pain
Mitigation: store provenance + allow re-chunking/retrofit jobs.

---

## 15. Proposed module boundaries (so it stays sane)

Suggested structure (names flexible):
- `corpus.py` (or inside `artifactor.py` as `Corpus` class):
  - ingest_* functions
  - upsert_chunk(s)
  - search(query, scope, filters)
  - rank_and_assemble_context_pack
- `context.py`:
  - build_model_input (chat history assembly)
  - inject_context_pack (retrieval integration)
- `main.py`:
  - API endpoints: search, metadata edit, context preview

The key constraint: **one canonical data shape** for “model input” and “context preview.”

---

## 16. What “done” means for MVP

MVP is done when:
- You can ask: “what did we decide about zeitgeber stripping?” and it reliably finds the relevant chunks.
- The context panel shows the retrieved chunks that were actually sent.
- You can edit tags/significance on a chunk and see retrieval change afterward.
- Web search results are clearly labeled and do not persist forever unless promoted.

---

## 17. Next steps (implementation order)

1) Create tables + triggers
2) Ingest messages + artifacts + memories
3) Implement `/api/corpus/search`
4) Implement context pack assembly
5) Inject into chat endpoints
6) Implement transparency in UI
7) Add edit endpoint
8) Add retrofit script
9) Optional: web cache ingestion

---

### Companion docs
- “WyrmGPT Corpus Retrieval (RAG) Design Doc” (DB-focused)

This document is the **spec guide**. If implementation decisions conflict with it, update the spec first (or you’ll end up with two realities again).

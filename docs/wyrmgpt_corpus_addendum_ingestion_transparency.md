# Addendum: Corpus Ingestion Policy & Transparency UX Patterns

This addendum captures design patterns that were not fully spelled out in the earlier docs:
1) how to ingest without drowning in message noise, and  
2) how to make the transparency panel useful instead of a wall of receipts.

This is intended to be “rehydration-ready” in a future session.

---

## 1) Ingestion without drowning in message noise

### 1.1 Principle: “retrieval objects” are not the same as “all objects”
Messages are abundant, repetitive, and often low-value. A good corpus is selective by default.

**Default stance:** ingest (index) everything that is authoritative and curated; ingest chat selectively.

### 1.2 Two-tier retrieval strategy: “Hot context” + “Cold corpus”
Instead of indexing every message forever, separate:
- **Hot context**: last N messages of the current conversation (no corpus storage required)
- **Cold corpus**: curated/important chunks (memories, authored artifacts, promoted messages, selected files)

Operationally:
- Hot context is included automatically by the normal chat transcript.
- Cold corpus is retrieved by query.

This drastically reduces the need to “corpus” every message and keeps ranking stable.

### 1.3 Promotion-based chat ingestion (recommended MVP default)
Only ingest messages into corpus when:
- user clicks “Promote” / “Save”
- a rule triggers (see 1.4)
- the message becomes part of a summary/memory

Benefits:
- avoids noise
- creates intentional curation
- user sees cause/effect (“I promoted this; it now appears in retrieval”)

### 1.4 Rule-based message ingestion (optional, safe rules)
If you want some automation without chaos, limit it to obvious high-signal cases:

- **Decision markers**: messages containing “decision”, “we will”, “we decided”, “MVP”, “ship”
- **Code markers**: stack traces, file paths, function names (regex heuristics)
- **User-labeled**: any message with “remember this” or “pin”
- **High significance**: a classifier can propose `meta_significance`, but should not auto-promote without user approval (MVP)

### 1.5 Rolling summaries as a compression pattern (powerful and cheap)
Use conversation summarization as the canonical long-term chat memory:
- every K messages, create/update a “conversation summary” memory (curated by default)
- summary becomes a corpus item (`source_type='memory'`)
- raw messages remain in DB but are not all indexed

This yields excellent recall without indexing thousands of trivial utterances.

### 1.6 Chunk granularity defaults
For messages:
- default 1 message = 1 chunk
- only split if > X chars/tokens (rare)
For files/artifacts:
- split by semantic boundaries (headings/paragraphs)
For memories:
- split if long; otherwise single chunk

### 1.7 De-duplication at ingestion time
To avoid “same chunk, many times,” compute a stable hash:
- `meta_hash = sha256(normalized_text)`
- unique constraint on (`source_key`, `chunk_index`) for structural identity
- optional unique constraint on hash within scope to stop duplicates

### 1.8 Practical MVP ingestion policy (recommended)
- Always ingest: files (as you already do), memories, curated artifacts
- Ingest chat: only promoted messages + rolling summary memory
- Web: cache only when web search is invoked; apply TTL; do not auto-promote

---

## 2) Transparency panel patterns (useful, not overwhelming)

### 2.1 Principle: “show the receipt, not the warehouse”
Transparency should answer:
- What did you use?
- Where did it come from?
- Why did you pick it?
- How can I change this?

It should not dump raw prompt blobs unless requested.

### 2.2 Two-layer UI: “Summary view” + “Drill-down view”
Default view: compact list of retrieved items:
- rank #
- source badge (memory/file/chat/web)
- title/snippet
- score summary (one line)
- quick actions (pin/promote, tag, raise/lower significance, exclude)

Drill-down on click:
- full chunk text
- provenance (source link, created_at, chunk_index)
- scoring breakdown (bm25 + boosts)
- raw metadata JSON (optional)
- “Show in context pack” highlighting

### 2.3 “Context pack” vs “Candidate set” separation
Show two lists:
- **Candidates**: top K retrieved results (maybe 30)
- **Used**: the subset that actually went into the model prompt (maybe 8–20)

This prevents a common confusion: “it found it, why didn’t it use it?”

### 2.4 Score explanations that don’t lie
Keep explanations coarse but true:
- “text match”
- “tag match”
- “curated”
- “high significance”
- “recent”
- “web (fresh)”

Avoid fake precision. If you don’t expose weights, just show the components.

### 2.5 User control knobs (MVP-friendly)
Minimum knobs:
- edit tags (`meta_tags_json`)
- edit significance (`meta_significance`)
- set curated override (`meta_curated_override`)
- exclude (future): `meta_excluded=1` or per-conversation exclude list

### 2.6 “Promote” and “Demote” patterns
Promote actions:
- message → corpus chunk (source_type='message', curated override true, significance raised)
- web → memory/artifact (copy content into a curated source_type and delete/expire the web chunk)

Demote actions:
- lower significance
- set curated override false
- exclude (optional)

### 2.7 Progressive disclosure for raw prompt
The transparency mission often tempts dumping the whole prompt.
Instead:
- show the “Used chunks” list by default
- provide a toggle: “Show raw prompt sent to model”
- show another toggle: “Show system prompt” (if you allow it)

This prevents “wall of text” while still meeting transparency requirements.

### 2.8 Debug mode vs normal mode
Have a UI toggle:
- Normal: compact, human-friendly
- Debug: show everything (IDs, hashes, raw JSON, token counts)

This keeps the product friendly without hiding power.

---

## 3) A tight MVP UX blueprint (doable in 1–2 days)

1) After each response, store `used_corpus_chunk_ids` in response metadata
2) UI renders a “Retrieved Context” panel with:
   - “Used” list (top N included)
   - “Candidates” list (optional collapsed)
3) Clicking an item opens details (modal or right panel)
4) Edits (tags/significance/curated override) call a simple endpoint and update UI live

---

## 4) Rehydration checklist (what future-you needs)

- The ingestion policy defaults (1.8)
- The two-tier strategy (hot vs cold)
- The transparency UI split (used vs candidates; summary vs drill-down)
- The core user knobs (tags, significance, curated override)
- The promotion/demotion semantics

If these remain true, the implementation can evolve without losing the philosophy.


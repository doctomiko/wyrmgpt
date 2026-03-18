
# WyrmGPT Web RAG + Citations Architecture (Phase 6A Internal Plan)

## Purpose
Add external web retrieval, persistent citation receipts, and a structured source pipeline while preserving the existing artifact → corpus_chunks → embedding → retrieval system.

This document describes the **data model and architectural design**.

Pipeline:
web search → web_source_snapshot → artifact → corpus_chunks → embeddings → retrieval → citations

## Entities

### Web Sources
Represents a canonical external resource (URL).

Fields:
- id
- canonical_url
- domain
- first_seen_at
- created_by
- project_id

### Web Source Snapshots
Fetched version of the source.

Fields:
- id
- source_id
- fetched_at
- fetch_method
- http_status
- raw_html
- headers_json
- ttl_seconds
- is_pinned
- expired_at

### Citations
Persistent evidence used for a response.

Fields:
- id
- assistant_message_id
- corpus_chunk_id
- artifact_id
- source_type
- source_locator
- retrieval_rank
- retrieval_score
- highlight_start
- highlight_end
- created_at

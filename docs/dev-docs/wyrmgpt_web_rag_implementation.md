
# WyrmGPT Web RAG + Citations Implementation Guide

## Database Changes

CREATE TABLE web_sources (
 id INTEGER PRIMARY KEY,
 canonical_url TEXT,
 domain TEXT,
 project_id INTEGER,
 first_seen_at TEXT,
 created_by TEXT
);

CREATE TABLE web_source_snapshots (
 id INTEGER PRIMARY KEY,
 source_id INTEGER,
 fetched_at TEXT,
 fetch_method TEXT,
 http_status INTEGER,
 raw_html TEXT,
 headers_json TEXT,
 ttl_seconds INTEGER,
 is_pinned INTEGER,
 expired_at TEXT
);

CREATE TABLE citations (
 id INTEGER PRIMARY KEY,
 assistant_message_id INTEGER,
 corpus_chunk_id INTEGER,
 artifact_id INTEGER,
 source_type TEXT,
 source_locator TEXT,
 retrieval_rank INTEGER,
 retrieval_score REAL,
 highlight_start INTEGER,
 highlight_end INTEGER,
 created_at TEXT
);

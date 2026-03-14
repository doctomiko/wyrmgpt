# Addendum: Corpus Design Changes (Design B + Naming + Generated Fields + Curation Taxonomy)

This addendum updates the earlier Corpus/RAG docs with the **Design B** decision (promote `artifacts` into Corpus), plus clarified naming conventions and the finalized **curation override** pattern.

It’s intentionally short so we can merge it into the larger vision/spec later.

---

## 1) SQLite “virtual columns” (generated columns)

SQLite supports **generated columns** (computed columns) in modern versions (SQLite 3.31+). A generated column can be:

- **VIRTUAL**: computed when read (no storage)
- **STORED**: computed when written (stored on disk)

Generated columns are ideal for deterministic derived fields like `source_key` and “effective” booleans such as `meta_curated`.

Notes:
- Generated columns can reference other columns in the same row.
- If your SQLite build is older or if you want maximal portability, you can compute these values in application code instead. The schema below assumes generated columns are available.

---

## 2) Design B (final): Promote `artifacts` → `corpus_chunks`

We will **rename/repurpose** the existing `artifacts` table into the unified Corpus chunk substrate (recommended name: `corpus_chunks` or `corpus_items`).

Key outcomes:
- **One table stores chunk text** used for retrieval and context packs.
- Full-text search (FTS5) and future embedding/vector metadata attach to this same table.
- No second chunk table, no duplication of text blobs.

Artifacts as a *concept* becomes:
- Either a `source_type='artifact'` (curated authored docs)
- Or a subset flagged as curated (`meta_curated = 1`)
- Or both (recommended: both are possible)

---

## 3) Naming conventions (final)

To keep schemas self-documenting and keep related columns grouped:

- **Scope** columns use `scope_` prefix:  
  `scope_project_id`, `scope_conversation_id` (and later `scope_user_id` if needed)
- **Metadata** columns use `meta_` prefix:  
  `meta_tags_json`, `meta_significance`, `meta_provenance_json`, `meta_expires_at`, etc.

This improves:
- readability and maintenance
- bulk edits / migrations
- UI inspection panels (metadata is a contiguous block)

---

## 4) `source_key` as a generated column (recommended)

Because you have both int and uuid/text identifiers in different source tables, Corpus rows must support:
- `source_id` (INTEGER) and
- `source_uuid` (TEXT)

Canonical identity rule:
- If `source_uuid` is present: `"{source_type}:{source_uuid}"`
- Else: `"{source_type}#:{source_id}"`

Recommended generated column:

```sql
source_key TEXT GENERATED ALWAYS AS (
  CASE
    WHEN source_uuid IS NOT NULL AND source_uuid <> ''
      THEN source_type || ':' || source_uuid
    ELSE source_type || '#:' || CAST(source_id AS TEXT)
  END
) VIRTUAL
```

Performance note: use `STORED` instead of `VIRTUAL` if you find this is a hotspot on large corpora.

---

## 5) Curation: default + override + effective (final pattern)

We are separating **taxonomy defaults** (“curated by origin class”) from **manual promotion** (“curated by human decision”).

### 5.1 Definitions

- `meta_curated_default` (generated): computed from source taxonomy
- `meta_curated_override` (stored nullable): manual boolean flip (0/1), NULL means “no override”
- `meta_curated` (generated effective): uses override when present, else default

This gives you:
- clean defaults
- explicit human override
- one “effective truth” column used everywhere

### 5.2 Recommended taxonomy defaults

Default curated **true**:
- `source_type IN ('memory', 'artifact')`

Default curated **false**:
- `source_type IN ('file', 'message', 'web')`

Rationale:
- Memories and authored artifacts are the most likely to be canonical.
- Files are authoritative but not inherently curated; specific chunks can be promoted.
- Messages are noisy; promotion should be explicit.
- Web is ephemeral by default; promotion should be explicit.

### 5.3 Schema expressions

```sql
meta_curated_default INTEGER GENERATED ALWAYS AS (
  CASE WHEN source_type IN ('memory','artifact') THEN 1 ELSE 0 END
) VIRTUAL;

meta_curated_override INTEGER NULL
  CHECK (meta_curated_override IN (0,1) OR meta_curated_override IS NULL);

meta_curated INTEGER GENERATED ALWAYS AS (
  CASE
    WHEN meta_curated_override IS NOT NULL THEN meta_curated_override
    ELSE meta_curated_default
  END
) VIRTUAL;
```

---

## 6) Significance and expiry (confirmed)

- `meta_significance` stays independent of curated.  
  Curated is a strong prior; significance is a softer rank signal and is user-editable.
- `meta_expires_at` is supported for any row, but **only web defaults to using it**.  
  Web results typically get a TTL; internal corpus items usually do not unless explicitly set.

---

## 7) MVP impact (unchanged)

This addendum does not increase MVP scope; it clarifies the schema and invariants so we don’t create two overlapping truth systems.

MVP remains:
- FTS5 + scope + metadata boosts
- corpusing files + memories first
- optional promotion workflow for messages and web

---

## 8) Retrieval scoring implication (one-liner)

Because `meta_curated` is the effective truth, ranking code can simply:
- apply a curated prior if `meta_curated=1`
- use `meta_significance` as a continuous multiplier
- use `meta_expires_at` to filter or down-weight expired web items

No repeated COALESCE logic in queries.


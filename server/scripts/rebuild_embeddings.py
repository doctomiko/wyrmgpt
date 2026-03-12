from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.db import _force_schema_regression_if_table_missing, db_session, init_schema, upsert_chunk_embedding_state, _sha256_hex
from server.config import load_embedding_config, load_vector_config
from server.providers.openai_embeddings import OpenAIEmbeddingProvider
from server.vector.qdrant_local import QdrantLocalVectorStore
from server.vector.base import VectorRecord

BATCH_SIZE = 100

def main() -> None:
    _force_schema_regression_if_table_missing(17, "chunk_embedding_state")
    init_schema()

    emb_cfg = load_embedding_config()
    vec_cfg = load_vector_config()
    provider = OpenAIEmbeddingProvider(emb_cfg=emb_cfg)
    store = QdrantLocalVectorStore(cfg=vec_cfg)

    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id AS chunk_id,
                c.artifact_id,
                c.scope_key,
                c.source_kind,
                c.source_id,
                c.file_id,
                c.filename,
                c.chunk_index,
                c.text
            FROM corpus_chunks c
            ORDER BY c.id
            """
        ).fetchall()

    batch: list[dict] = []
    for row in rows:
        batch.append(dict(row))
        if len(batch) >= BATCH_SIZE:
            process_batch(batch, provider, store, emb_cfg)
            batch.clear()

    if batch:
        process_batch(batch, provider, store, emb_cfg)

def process_batch(batch, provider, store, emb_cfg):
    texts = [r["text"] for r in batch]
    vectors = provider.embed_documents(texts)
    if not vectors:
        return

    store.ensure_collection(store.cfg.collection_name, len(vectors[0]))

    items: list[VectorRecord] = []
    for row, vec in zip(batch, vectors):
        text_hash = _sha256_hex((row.get("text") or "").strip())
        items.append(
            VectorRecord(
                chunk_id=int(row["chunk_id"]),
                vector=vec,
                payload={
                    "chunk_id": int(row["chunk_id"]),
                    "artifact_id": row.get("artifact_id") or "",
                    "scope_key": row.get("scope_key") or "",
                    "source_kind": row.get("source_kind") or "",
                    "source_id": row.get("source_id") or "",
                    "file_id": row.get("file_id") or "",
                    "filename": row.get("filename") or "",
                    "chunk_index": int(row.get("chunk_index") or 0),
                    "text_hash": text_hash,
                },
            )
        )

    store.upsert_chunks(items)

    for row, vec in zip(batch, vectors):
        upsert_chunk_embedding_state(
            chunk_id=int(row["chunk_id"]),
            text_hash=_sha256_hex((row.get("text") or "").strip()),
            embedding_provider=emb_cfg.provider,
            embedding_model=emb_cfg.model,
            vector_dim=len(vec),
            status="ready",
        )

if __name__ == "__main__":
    main()
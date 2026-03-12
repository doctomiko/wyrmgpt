from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.db import (
    init_schema,
    list_corpus_chunks_requiring_embeddings,
    upsert_chunk_embedding_state,
)
from server.config import load_embedding_config, load_vector_config
from server.providers.openai_embeddings import OpenAIEmbeddingProvider
from server.vector.qdrant_local import QdrantLocalVectorStore
from server.vector.base import VectorRecord


def main() -> None:
    init_schema()

    emb_cfg = load_embedding_config()
    vec_cfg = load_vector_config()

    if emb_cfg.provider != "openai":
        raise NotImplementedError(
            f"Embedding provider not implemented in rebuild script yet: {emb_cfg.provider}"
        )

    provider = OpenAIEmbeddingProvider(emb_cfg=emb_cfg)
    store = QdrantLocalVectorStore(cfg=vec_cfg)

    pending = list_corpus_chunks_requiring_embeddings(
        embedding_provider=emb_cfg.provider,
        embedding_model=emb_cfg.model,
        vector_dim=int(emb_cfg.dimensions or 0),
    )

    total = len(pending)
    print(f"Chunks needing embeddings: {total}")
    if total == 0:
        print("Nothing to do.")
        return

    batch_size = max(1, int(emb_cfg.batch_size or 64))
    processed = 0

    for start in range(0, total, batch_size):
        batch = pending[start : start + batch_size]
        done = process_batch(batch, provider, store, emb_cfg)
        processed += done
        print(f"Embedded {processed}/{total} chunks")

    print("Embedding rebuild complete.")


def process_batch(batch, provider, store, emb_cfg) -> int:
    rows_to_embed: list[dict] = []
    texts: list[str] = []

    for row in batch:
        text = (row.get("text") or "").strip()
        if not text:
            upsert_chunk_embedding_state(
                chunk_id=int(row["chunk_id"]),
                text_hash=row["text_hash"],
                embedding_provider=emb_cfg.provider,
                embedding_model=emb_cfg.model,
                vector_dim=0,
                status="empty",
            )
            continue

        rows_to_embed.append(row)
        texts.append(text)

    if not rows_to_embed:
        return 0

    vectors = provider.embed_documents(texts)
    if len(vectors) != len(rows_to_embed):
        raise RuntimeError(
            f"Embedding provider returned {len(vectors)} vectors for {len(rows_to_embed)} texts"
        )

    store.ensure_collection(store.cfg.collection_name, len(vectors[0]))

    items: list[VectorRecord] = []
    for row, vec in zip(rows_to_embed, vectors):
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
                    "text_hash": row["text_hash"],
                },
            )
        )

    store.upsert_chunks(items)

    for row, vec in zip(rows_to_embed, vectors):
        upsert_chunk_embedding_state(
            chunk_id=int(row["chunk_id"]),
            text_hash=row["text_hash"],
            embedding_provider=emb_cfg.provider,
            embedding_model=emb_cfg.model,
            vector_dim=len(vec),
            status="ready",
        )

    return len(rows_to_embed)


if __name__ == "__main__":
    main()
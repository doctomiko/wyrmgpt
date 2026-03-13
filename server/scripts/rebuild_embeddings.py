from datetime import datetime, timezone
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.db import (
    db_session,
    init_schema,
    list_corpus_chunks_requiring_embeddings,
)
from server.config import load_embedding_config, load_vector_config
from server.providers.openai_embeddings import OpenAIEmbeddingProvider
from server.vector.qdrant_local import QdrantLocalVectorStore
from server.vector.base import VectorRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _bulk_upsert_chunk_embedding_state(
    rows: list[tuple[int, str, str, str, int, str, str]]
) -> None:
    if not rows:
        return

    with db_session() as conn:
        conn.executemany(
            """
            INSERT INTO chunk_embedding_state(
                chunk_id, text_hash, embedding_provider, embedding_model,
                vector_dim, last_embedded_at, status
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                text_hash = excluded.text_hash,
                embedding_provider = excluded.embedding_provider,
                embedding_model = excluded.embedding_model,
                vector_dim = excluded.vector_dim,
                last_embedded_at = excluded.last_embedded_at,
                status = excluded.status
            """,
            rows,
        )


def main() -> None:
    started = time.perf_counter()
    init_schema()

    emb_cfg = load_embedding_config()
    vec_cfg = load_vector_config()

    if emb_cfg.provider != "openai":
        raise NotImplementedError(
            f"Embedding provider not implemented in rebuild script yet: {emb_cfg.provider}"
        )

    if vec_cfg.backend != "qdrant_local":
        raise NotImplementedError(
            f"Vector backend not implemented in rebuild script yet: {vec_cfg.backend}"
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
    empty_marked = 0
    collection_ready = False
    last_report = time.perf_counter()

    for start in range(0, total, batch_size):
        batch = pending[start : start + batch_size]
        done, empties, ensured = process_batch(
            batch=batch,
            provider=provider,
            store=store,
            emb_cfg=emb_cfg,
            collection_ready=collection_ready,
        )
        processed += done
        empty_marked += empties
        collection_ready = collection_ready or ensured

        now = time.perf_counter()
        if (now - last_report) >= 1.0 or processed + empty_marked >= total:
            elapsed = now - started
            rate = (processed + empty_marked) / elapsed if elapsed > 0 else 0.0
            print(
                f"Processed {processed + empty_marked}/{total} "
                f"(embedded={processed}, empty={empty_marked}, rate={rate:.1f}/s)"
            )
            last_report = now

    elapsed = time.perf_counter() - started
    print(
        f"Embedding rebuild complete. "
        f"embedded={processed}, empty={empty_marked}, total={total}, elapsed={elapsed:.1f}s"
    )


def process_batch(
    *,
    batch: list[dict],
    provider: OpenAIEmbeddingProvider,
    store: QdrantLocalVectorStore,
    emb_cfg,
    collection_ready: bool,
) -> tuple[int, int, bool]:
    rows_to_embed: list[dict] = []
    texts: list[str] = []
    state_rows: list[tuple[int, str, str, str, int, str, str]] = []
    timestamp = _now_iso()

    for row in batch:
        text = (row.get("text") or "").strip()
        if not text:
            state_rows.append(
                (
                    int(row["chunk_id"]),
                    row["text_hash"],
                    emb_cfg.provider,
                    emb_cfg.model,
                    0,
                    timestamp,
                    "empty",
                )
            )
            continue

        rows_to_embed.append(row)
        texts.append(text)

    embedded_count = 0
    ensured_now = False

    if rows_to_embed:
        vectors = provider.embed_documents(texts)
        if len(vectors) != len(rows_to_embed):
            raise RuntimeError(
                f"Embedding provider returned {len(vectors)} vectors for {len(rows_to_embed)} texts"
            )

        if not collection_ready:
            store.ensure_collection(store.cfg.collection_name, len(vectors[0]))
            ensured_now = True

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
            state_rows.append(
                (
                    int(row["chunk_id"]),
                    row["text_hash"],
                    emb_cfg.provider,
                    emb_cfg.model,
                    len(vec),
                    timestamp,
                    "ready",
                )
            )

        store.upsert_chunks(items)
        embedded_count = len(items)

    _bulk_upsert_chunk_embedding_state(state_rows)
    empty_count = len(batch) - len(rows_to_embed)

    return embedded_count, empty_count, ensured_now


if __name__ == "__main__":
    main()
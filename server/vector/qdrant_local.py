from pathlib import Path

from qdrant_client import QdrantClient, models

from ..config import VectorConfig, load_vector_config
from .base import VectorHit, VectorRecord


class QdrantLocalVectorStore:
    def __init__(self, cfg: VectorConfig | None = None) -> None:
        self.cfg = cfg or load_vector_config()
        Path(self.cfg.local_path).mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=self.cfg.local_path)

    def ensure_collection(self, name: str, dimension: int) -> None:
        if self.client.collection_exists(name):
            return

        self.client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=dimension,
                distance=models.Distance.COSINE,
            ),
        )

    def upsert_chunks(self, items: list[VectorRecord]) -> None:
        if not items:
            return

        points = [
            models.PointStruct(
                id=int(item.chunk_id),
                vector=item.vector,
                payload=item.payload,
            )
            for item in items
        ]
        self.client.upsert(
            collection_name=self.cfg.collection_name,
            points=points,
        )

    def delete_by_chunk_ids(self, chunk_ids: list[int]) -> None:
        if not chunk_ids:
            return

        self.client.delete(
            collection_name=self.cfg.collection_name,
            points_selector=models.PointIdsList(
                points=[int(x) for x in chunk_ids]
            ),
        )

    def _build_filter(
        self,
        *,
        scope_keys: list[str] | None,
        transcript_ids: list[str] | None,
    ) -> models.Filter | None:
        should: list[models.Condition] = []

        if scope_keys:
            should.append(
                models.FieldCondition(
                    key="scope_key",
                    match=models.MatchAny(any=list(scope_keys)),
                )
            )

        if transcript_ids:
            should.append(
                models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_kind",
                            match=models.MatchValue(value="conversation:transcript"),
                        ),
                        models.FieldCondition(
                            key="source_id",
                            match=models.MatchAny(any=list(transcript_ids)),
                        ),
                    ]
                )
            )

        if not should:
            return None

        return models.Filter(should=should)

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        scope_keys: list[str] | None = None,
        transcript_ids: list[str] | None = None,
    ) -> list[VectorHit]:
        if not query_vector:
            return []

        query_filter = self._build_filter(
            scope_keys=scope_keys,
            transcript_ids=transcript_ids,
        )

        resp = self.client.query_points(
            collection_name=self.cfg.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=max(1, int(top_k)),
            with_payload=True,
        )

        points = getattr(resp, "points", resp)
        out: list[VectorHit] = []
        for p in points:
            if isinstance(p, tuple):
                if len(p) == 3:
                    point_id, payload, score = p
                else:
                    point_id, payload = p
                    score = 0.0
                payload = dict(payload or {})
            else:
                payload = dict(p.payload or {})
                point_id = p.id
                score = p.score
            out.append(
                VectorHit(
                    chunk_id=int(payload.get("chunk_id") or point_id),
                    score=float(score),
                    payload=payload,
                )
            )
        return out
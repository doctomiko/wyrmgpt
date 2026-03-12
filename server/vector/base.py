from dataclasses import dataclass
from typing import Any, Protocol

@dataclass
class VectorRecord:
    chunk_id: int
    vector: list[float]
    payload: dict[str, Any]

@dataclass
class VectorHit:
    chunk_id: int
    score: float
    payload: dict[str, Any]

class VectorStore(Protocol):
    def ensure_collection(self, name: str, dimension: int) -> None: ...
    def upsert_chunks(self, items: list[VectorRecord]) -> None: ...
    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int,
        scope_keys: list[str] | None = None,
        transcript_ids: list[str] | None = None,
    ) -> list[VectorHit]: ...
    def delete_by_chunk_ids(self, chunk_ids: list[int]) -> None: ...
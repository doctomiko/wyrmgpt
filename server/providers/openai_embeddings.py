from openai import OpenAI

from ..config import (
    EmbeddingConfig,
    OpenAIConfig,
    load_embedding_config,
    load_openai_config,
)

class OpenAIEmbeddingProvider:
    def __init__(
        self,
        emb_cfg: EmbeddingConfig | None = None,
        oai_cfg: OpenAIConfig | None = None,
    ) -> None:
        self.emb_cfg = emb_cfg or load_embedding_config()
        self.oai_cfg = oai_cfg or load_openai_config()
        self.client = OpenAI(api_key=self.oai_cfg.open_ai_apikey)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        cleaned = [str(t).strip() for t in texts if str(t).strip()]
        if not cleaned:
            return []

        kwargs: dict[str, list[str] | str | int] = {
            "input": cleaned,
            "model": self.emb_cfg.model,
        }
        if self.emb_cfg.dimensions > 0:
            kwargs["dimensions"] = self.emb_cfg.dimensions

        resp = self.client.embeddings.create(**kwargs)  # type: ignore
        return [item.embedding for item in resp.data]

    def embed_query(self, text: str) -> list[float]:
        cleaned = (text or "").strip()
        if not cleaned:
            return []

        kwargs: dict[str, str | int] = {
            "input": cleaned,
            "model": self.emb_cfg.model,
        }
        if self.emb_cfg.dimensions > 0:
            kwargs["dimensions"] = self.emb_cfg.dimensions

        resp = self.client.embeddings.create(**kwargs)  # type: ignore
        return resp.data[0].embedding
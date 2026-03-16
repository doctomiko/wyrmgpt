from typing import Any

from openai import OpenAI
from ..config import (
    EmbeddingConfig,
    OpenAIConfig,
    load_embedding_config,
    load_openai_config,
    load_provider_defs,
)
from .types import ProviderDef


def _resolve_embedding_provider_def(
    emb_cfg: EmbeddingConfig,
    oai_cfg: OpenAIConfig,
) -> ProviderDef:
    providers = load_provider_defs()
    requested = (emb_cfg.provider or "openai").strip()

    provider_def = providers.get(requested)
    if provider_def is not None:
        return provider_def

    if requested == "openai":
        return ProviderDef(
            id="openai",
            type="openai",
            api_key=oai_cfg.open_ai_apikey,
            base_url="https://api.openai.com/v1",
            enabled=True,
        )

    raise RuntimeError(f"Embedding provider is not configured: {requested}")


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        emb_cfg: EmbeddingConfig | None = None,
        oai_cfg: OpenAIConfig | None = None,
    ) -> None:
        self.emb_cfg = emb_cfg or load_embedding_config()
        self.oai_cfg = oai_cfg or load_openai_config()

        self.provider_def = _resolve_embedding_provider_def(self.emb_cfg, self.oai_cfg)

        api_key = (self.provider_def.api_key or "").strip()
        if not api_key and self.provider_def.type in ("ollama", "lmstudio", "openai_compat"):
            api_key = "local-not-needed"
        if not api_key and self.provider_def.type == "openai":
            api_key = self.oai_cfg.open_ai_apikey

        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if (self.provider_def.base_url or "").strip():
            kwargs["base_url"] = self.provider_def.base_url.strip()

        self.client = OpenAI(**kwargs)

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

        resp = self.client.embeddings.create(**kwargs)  # type: ignore[arg-type]
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

        resp = self.client.embeddings.create(**kwargs)  # type: ignore[arg-type]
        return resp.data[0].embedding

if (False):
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

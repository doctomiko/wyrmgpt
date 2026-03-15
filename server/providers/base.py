from typing import Iterator, Protocol
from .types import ChatResult, ModelInfo, ModelInput, ProviderDef, ResolvedDeployment


class ChatProvider(Protocol):
    def complete(self, deployment: ResolvedDeployment, model_input: ModelInput) -> ChatResult:
        ...

    def stream_text(self, deployment: ResolvedDeployment, model_input: ModelInput) -> Iterator[str]:
        ...


class ModelCatalogProvider(Protocol):
    def list_models(self, provider: ProviderDef) -> list[ModelInfo]:
        ...


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...

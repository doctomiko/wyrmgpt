from __future__ import annotations

from typing import Callable

from server.config import load_deployment_defs, load_provider_defs

from .anthropic_provider import AnthropicProvider
from .base import ChatProvider, ModelCatalogProvider
from .google_provider import GoogleProvider
from .openai_provider import OpenAIProvider
from .registry import ProviderRegistry
from .types import ModelCatalog, ProviderDef


def build_provider_registry(model_catalog: ModelCatalog | None = None) -> ProviderRegistry:
    model_catalog = model_catalog or {}
    providers = load_provider_defs()
    deployments = load_deployment_defs()

    compat_factory = lambda provider_def: OpenAIProvider(provider_def, model_catalog=model_catalog)
    google_factory = lambda provider_def: GoogleProvider(provider_def, model_catalog=model_catalog)
    anthropic_factory = lambda provider_def: AnthropicProvider(provider_def, model_catalog=model_catalog)

    chat_factories: dict[str, Callable[[ProviderDef], ChatProvider]] = {
        'openai': compat_factory,
        'ollama': compat_factory,
        'lmstudio': compat_factory,
        'openai_compat': compat_factory,
        'google': google_factory,
        'anthropic': anthropic_factory,
    }

    catalog_factories: dict[str, Callable[[ProviderDef], ModelCatalogProvider]] = {
        'openai': compat_factory,
        'ollama': compat_factory,
        'lmstudio': compat_factory,
        'openai_compat': compat_factory,
        'google': google_factory,
        'anthropic': anthropic_factory,
    }

    return ProviderRegistry(
        providers=providers,
        deployments=deployments,
        chat_factories=chat_factories,
        catalog_factories=catalog_factories,
    )

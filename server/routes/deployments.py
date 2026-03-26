import json
from pathlib import Path
from typing import Any, Callable
import time
from fastapi import HTTPException

from server.config import load_deployment_defs, load_provider_defs
from server.providers.base import ChatProvider, ModelCatalogProvider
from server.providers.openai_provider import OpenAIProvider
from server.providers.registry import ProviderRegistry
from server.providers.types import ModelCatalog, ModelInput, ProviderDef

from server.routes.base import app
import server.runtime as runtime

# region Model / Deployment selection runtime

# Legacy support checking for models
_MODELS_CACHE: dict[str, Any] | None = None
# TODO make these part of provider registry settings
_MODELS_CACHE_TS: float = 0.0
_MODELS_TTL_SECONDS = 300  # 5 minutes
# Newer deployment cache settings
_DEPLOYMENTS_CACHE: dict[str, Any] | None = None
_DEPLOYMENTS_CACHE_TS: float = 0.0

# endregion

# region Provider / Deployment helpers

def _require_provider_registry() -> ProviderRegistry:
    registry = runtime.PROVIDER_REGISTRY
    if registry is None:
        raise HTTPException(status_code=500, detail="Provider registry is not initialized.")
    return registry


def resolve_utility_target(
    *preferred_deployment_ids: str,
    fallback_model: str | None = None,
    required_capability: str = "chat",
    registry: ProviderRegistry | None = runtime.PROVIDER_REGISTRY
):
    
    if registry is None:
        raise RuntimeError("Provider registry is not initialized.")

    for deployment_id in preferred_deployment_ids:
        did = (deployment_id or "").strip()
        if not did:
            continue
        if did in registry.deployments:
            target = registry.get_deployment(did)
            if required_capability and not registry.has_capability(target, required_capability):
                continue
            return target

    requested = (fallback_model or "").strip()
    if requested:
        if requested in registry.deployments:
            target = registry.get_deployment(requested)
            if not required_capability or registry.has_capability(target, required_capability):
                return target
        else:
            target = registry.resolve_chat_target(requested)
            if not required_capability or registry.has_capability(target, required_capability):
                return target

    if required_capability:
        return registry.resolve_deployment_for_capability(
            required_capability,
            None,
            fallback_to_default_chat=True,
        )

    return registry.resolve_chat_target(None)


def _get_model_catalog() -> ModelCatalog:
    return runtime.MODEL_CATALOG


def build_provider_registry(
    model_catalog: ModelCatalog | None = None
) -> ProviderRegistry:
    model_catalog = model_catalog or runtime.MODEL_CATALOG
    providers = load_provider_defs()
    deployments = load_deployment_defs()

    compat_factory = lambda provider_def: OpenAIProvider(provider_def, model_catalog=model_catalog)

    chat_factories: dict[str, Callable[[ProviderDef], ChatProvider]] = {
        "openai": compat_factory,
        "ollama": compat_factory,
        "lmstudio": compat_factory,
        "openai_compat": compat_factory,
    }

    catalog_factories: dict[str, Callable[[ProviderDef], ModelCatalogProvider]] = {
        "openai": compat_factory,
        "ollama": compat_factory,
        "lmstudio": compat_factory,
        "openai_compat": compat_factory,
    }

    return ProviderRegistry(
        providers=providers,
        deployments=deployments,
        chat_factories=chat_factories,
        catalog_factories=catalog_factories,
    )


def load_model_catalog() -> ModelCatalog:
    #path = Path(__file__).parent / "model_catalog.json"
    #path = runtime.HERE / "model_catalog.json"
    path = runtime.MODEL_CATALOG_PATH
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print("Failed to load model_catalog.json:", e)
    return {}


def make_utility_completion(
    *preferred_deployment_ids: str,
    fallback_model: str | None = None,
    required_capability: str = "chat",
):
    registry = runtime.PROVIDER_REGISTRY
    if registry is None:
        raise RuntimeError("Provider registry is not initialized.")

    target = resolve_utility_target(
        *preferred_deployment_ids,
        fallback_model=fallback_model,
        required_capability=required_capability,
    )
    provider = registry.get_chat_provider(target)

    def complete_fn(system_prompt: str, user_prompt: str, max_output_tokens: int) -> str:
        model_input: ModelInput = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        request_options = {"max_output_tokens": max(1, int(max_output_tokens or 0))} if max_output_tokens else None
        result = provider.complete(target, model_input, request_options=request_options)
        return (result.text or "").strip()

    return complete_fn, target


def get_default_chat_target(
    registry: ProviderRegistry | None = None
):
    registry = registry or runtime.PROVIDER_REGISTRY
    if registry is None:
        raise RuntimeError("Provider registry is not initialized.")
    return registry.resolve_chat_target(None)


# endregion

# region Model Selection Endpoints

@app.get("/api/deployments")
def api_deployments(capability: str = "chat"):
    registry = _require_provider_registry()
    catalog = _get_model_catalog()

    try:
        cap = (capability or "").strip()
        deployments = (
            registry.list_deployments(cap)
            if cap and cap.lower() != "all"
            else registry.list_deployments(None)
        )

        items: list[dict[str, Any]] = []
        for d in deployments:
            meta = catalog.get(d.model, {})

            items.append(
                {
                    "id": d.id,
                    "display_name": d.display_name,
                    "provider_id": d.provider_id,
                    "provider_type": d.provider_type,
                    "model": d.model,
                    "capabilities": list(d.capabilities),
                    "tags": list(d.tags),
                    "enabled": d.enabled,
                    "base_url": d.base_url,
                    "is_legacy": d.id.startswith("legacy:"),
                    "vendor": meta.get("vendor", d.provider_id),
                    "description": meta.get("description", ""),
                    "input_cost_per_million": meta.get("input_cost_per_million"),
                    "output_cost_per_million": meta.get("output_cost_per_million"),
                    "context_window": meta.get("context_window"),
                }
            )

        items.sort(key=lambda x: (x["provider_id"], x["display_name"].lower()))
        return {
            "deployments": items,
            "capability": cap or "all",
            "cached": False,
            "fetched_at": int(time.time()),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to list deployments: {e}")


@app.get("/api/models")
def api_models():
    global _MODELS_CACHE, _MODELS_CACHE_TS
    now = time.time()
    if _MODELS_CACHE and (now - _MODELS_CACHE_TS) < _MODELS_TTL_SECONDS:
        return _MODELS_CACHE

    registry = _require_provider_registry()

    try:
        items: list[dict[str, Any]] = []

        for provider_id, provider_def in registry.providers.items():
            if not provider_def.enabled:
                continue

            try:
                catalog = registry.get_catalog_provider(provider_id)
                model_infos = catalog.list_models(provider_def)
            except Exception:
                continue

            for m in model_infos:
                mid = m.id

                items.append(
                    {
                        "id": m.id,
                        "provider_id": m.provider_id,
                        "provider_type": m.provider_type,
                        "created": m.created,
                        "owned_by": m.owned_by,
                        "vendor": m.vendor,
                        "display_name": m.display_name,
                        "description": m.description,
                        "input_cost_per_million": m.input_cost_per_million,
                        "output_cost_per_million": m.output_cost_per_million,
                        "context_window": m.context_window,
                        "tags": list(m.tags),
                    }
                )

        items.sort(key=lambda m: (m.get("vendor", ""), m["display_name"].lower()))
        payload = {"models": items, "cached": True, "fetched_at": int(now)}
        _MODELS_CACHE = payload
        _MODELS_CACHE_TS = now
        return payload
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to list models: {e}")

# endregion

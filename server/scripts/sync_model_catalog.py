from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.providers.factories import build_provider_registry
from server.providers.registry import ProviderRegistry
from server.providers.types import ModelCatalog


ALLOWED_OPENAI_PREFIXES = ("gpt-", "o1", "o3", "o4")


def load_model_catalog() -> ModelCatalog:
    path = ROOT / "server" / "model_catalog.json"
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


def provider_ids_with_catalog_support(registry: ProviderRegistry) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for dep in registry.deployments.values():
        if not dep.enabled:
            continue
        if not registry.has_capability(dep, "catalog"):
            continue

        provider = registry.providers.get(dep.provider)
        if not provider or not provider.enabled:
            continue

        if provider.id in seen:
            continue

        seen.add(provider.id)
        out.append(provider.id)

    return out


def model_allowed(provider_id: str, model_id: str) -> bool:
    if provider_id == "openai":
        return model_id.startswith(ALLOWED_OPENAI_PREFIXES)
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--provider",
        action="append",
        dest="providers",
        default=[],
        help="Specific provider id(s) to sync. Defaults to all enabled providers with a catalog-capable deployment.",
    )
    ap.add_argument(
        "--catalog-path",
        default=str(ROOT / "server" / "model_catalog.json"),
        help="Path to model_catalog.json",
    )
    args = ap.parse_args()

    catalog_path = Path(args.catalog_path)
    catalog = load_model_catalog()
    registry = build_provider_registry(catalog)

    provider_ids = [p.strip() for p in args.providers if p.strip()]
    if not provider_ids:
        provider_ids = provider_ids_with_catalog_support(registry)

    if not provider_ids:
        raise RuntimeError("No enabled providers with catalog capability are configured.")

    added = 0
    seen_models = 0
    touched_providers: list[str] = []

    for provider_id in provider_ids:
        provider_def = registry.providers.get(provider_id)
        if not provider_def:
            raise RuntimeError(f"Provider '{provider_id}' is not configured.")
        if not provider_def.enabled:
            print(f"Skipping disabled provider: {provider_id}")
            continue

        catalog_provider = registry.get_catalog_provider(provider_id)
        models = catalog_provider.list_models(provider_def)
        touched_providers.append(provider_id)

        for model in models:
            mid = (model.id or "").strip()
            if not mid:
                continue
            if not model_allowed(provider_id, mid):
                continue

            seen_models += 1
            existing = catalog.get(mid)
            if existing is None:
                catalog[mid] = {
                    "vendor": model.vendor,
                    "display_name": model.display_name or mid,
                    "description": model.description or "Auto-generated stub entry; fill in details if you actually use this.",
                    "input_cost_per_million": model.input_cost_per_million,
                    "output_cost_per_million": model.output_cost_per_million,
                    "context_window": model.context_window,
                    "tags": list(model.tags or ()) or ["auto-stub", f"provider:{provider_id}"],
                }
                added += 1
                continue

            if not existing.get("vendor") and model.vendor:
                existing["vendor"] = model.vendor
            if not existing.get("display_name") and model.display_name:
                existing["display_name"] = model.display_name
            if not existing.get("description") and model.description:
                existing["description"] = model.description
            if existing.get("context_window") is None and model.context_window is not None:
                existing["context_window"] = model.context_window
            if existing.get("input_cost_per_million") is None and model.input_cost_per_million is not None:
                existing["input_cost_per_million"] = model.input_cost_per_million
            if existing.get("output_cost_per_million") is None and model.output_cost_per_million is not None:
                existing["output_cost_per_million"] = model.output_cost_per_million

            tags = list(existing.get("tags") or [])
            if f"provider:{provider_id}" not in tags:
                tags.append(f"provider:{provider_id}")
            for t in model.tags or ():
                if t not in tags:
                    tags.append(t)
            existing["tags"] = tags

    catalog_path.write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Synced providers={touched_providers}; observed_models={seen_models}; "
        f"added={added}; catalog_size={len(catalog)}"
    )


if __name__ == "__main__":
    main()
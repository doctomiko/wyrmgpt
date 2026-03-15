from dataclasses import dataclass
from typing import Callable

from .base import ChatProvider, ModelCatalogProvider
from .types import ProviderDef, DeploymentDef, ResolvedDeployment


@dataclass
class ProviderRegistry:
    providers: dict[str, ProviderDef]
    deployments: dict[str, DeploymentDef]
    chat_factories: dict[str, Callable[[ProviderDef], ChatProvider]]
    catalog_factories: dict[str, Callable[[ProviderDef], ModelCatalogProvider]]

    def get_default_chat_deployment_id(self) -> str:
        if "chat_default" in self.deployments and self.deployments["chat_default"].enabled:
            return "chat_default"
        for deployment_id, dep in self.deployments.items():
            if dep.enabled and "chat" in dep.capabilities:
                return deployment_id
        raise ValueError("No enabled chat deployment is configured.")

    def list_enabled_deployments(self) -> list[ResolvedDeployment]:
        out: list[ResolvedDeployment] = []

        for dep in self.deployments.values():
            if not dep.enabled:
                continue
            provider = self.providers.get(dep.provider)
            if not provider or not provider.enabled:
                continue

            out.append(
                ResolvedDeployment(
                    id=dep.id,
                    provider_id=provider.id,
                    provider_type=provider.type,
                    model=dep.model,
                    display_name=dep.display_name or dep.model,
                    capabilities=dep.capabilities,
                    tags=dep.tags,
                    enabled=dep.enabled,
                    base_url=provider.base_url,
                )
            )

        return out

    def list_chat_deployments(self) -> list[ResolvedDeployment]:
        return [
            d for d in self.list_enabled_deployments()
            if "chat" in d.capabilities
        ]

    def get_deployment(self, deployment_id: str) -> ResolvedDeployment:
        dep = self.deployments.get(deployment_id)
        if not dep:
            raise ValueError(f"Deployment '{deployment_id}' is not configured.")
        if not dep.enabled:
            raise ValueError(f"Deployment '{deployment_id}' is disabled.")

        provider = self.providers.get(dep.provider)
        if not provider:
            raise ValueError(f"Provider '{dep.provider}' for deployment '{deployment_id}' is not configured.")
        if not provider.enabled:
            raise ValueError(f"Provider '{provider.id}' is disabled.")

        return ResolvedDeployment(
            id=dep.id,
            provider_id=provider.id,
            provider_type=provider.type,
            model=dep.model,
            display_name=dep.display_name or dep.model,
            capabilities=dep.capabilities,
            tags=dep.tags,
            enabled=dep.enabled,
            base_url=provider.base_url,
        )

    def resolve_chat_target(self, requested: str | None) -> ResolvedDeployment:
        requested = (requested or str(self.get_default_chat_deployment_id())).strip()
        if requested in self.deployments:
            dep = self.deployments[requested]
            if not dep.enabled:
                raise ValueError(f"Deployment '{requested}' is disabled.")
            provider = self.providers.get(dep.provider)
            if not provider:
                raise ValueError(f"Provider '{dep.provider}' for deployment '{requested}' is not configured.")
            if not provider.enabled:
                raise ValueError(f"Provider '{provider.id}' is disabled.")
            return ResolvedDeployment(
                id=dep.id,
                provider_id=provider.id,
                provider_type=provider.type,
                model=dep.model,
                display_name=dep.display_name or dep.model,
                capabilities=dep.capabilities,
                base_url=provider.base_url,
            )
        # Backward-compatibility path:
        # treat unknown requested value as a raw model string on the default provider.
        default_id = self.get_default_chat_deployment_id()
        default_dep = self.deployments[default_id]
        provider = self.providers.get(default_dep.provider)
        if not provider:
            raise ValueError(f"Default provider '{default_dep.provider}' is not configured.")

        return ResolvedDeployment(
            id=f"legacy:{requested}",
            provider_id=provider.id,
            provider_type=provider.type,
            model=requested,
            display_name=requested,
            capabilities=("chat", "stream"),
            tags=("legacy-model",),
            enabled=True,
            base_url=provider.base_url,
        )

    def get_chat_provider(self, deployment: ResolvedDeployment) -> ChatProvider:
        factory = self.chat_factories.get(deployment.provider_type)
        if not factory:
            raise ValueError(f"No chat provider factory registered for provider type '{deployment.provider_type}'.")
        provider_def = self.providers[deployment.provider_id]
        return factory(provider_def)

    def get_catalog_provider(self, provider_id: str) -> ModelCatalogProvider:
        provider_def = self.providers.get(provider_id)
        if not provider_def:
            raise ValueError(f"Provider '{provider_id}' is not configured.")
        factory = self.catalog_factories.get(provider_def.type)
        if not factory:
            raise ValueError(f"No catalog provider factory registered for provider type '{provider_def.type}'.")
        return factory(provider_def)

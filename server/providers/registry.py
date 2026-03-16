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

    def _resolve_from_def(self, dep: DeploymentDef) -> ResolvedDeployment:
        provider = self.providers.get(dep.provider)
        if not provider:
            raise ValueError(f"Provider '{dep.provider}' for deployment '{dep.id}' is not configured.")
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

    def has_capability(self, deployment: ResolvedDeployment | DeploymentDef, capability: str) -> bool:
        cap = (capability or "").strip().lower()
        if not cap:
            return True
        caps = tuple((c or "").strip().lower() for c in deployment.capabilities)
        return cap in caps

    def get_default_chat_deployment_id(self) -> str:
        if "chat_default" in self.deployments and self.deployments["chat_default"].enabled:
            dep = self.deployments["chat_default"]
            if self.has_capability(dep, "chat"):
                return "chat_default"

        for deployment_id, dep in self.deployments.items():
            if dep.enabled and self.has_capability(dep, "chat"):
                return deployment_id

        raise ValueError("No enabled chat deployment is configured.")

    def list_deployments(self, capability: str | None = None) -> list[ResolvedDeployment]:
        out: list[ResolvedDeployment] = []
        cap = (capability or "").strip().lower()

        for dep in self.deployments.values():
            if not dep.enabled:
                continue

            provider = self.providers.get(dep.provider)
            if not provider or not provider.enabled:
                continue

            if cap and not self.has_capability(dep, cap):
                continue

            out.append(self._resolve_from_def(dep))

        return out

    def list_chat_deployments(self) -> list[ResolvedDeployment]:
        return self.list_deployments("chat")

    def get_deployment(self, deployment_id: str) -> ResolvedDeployment:
        dep = self.deployments.get(deployment_id)
        if not dep:
            raise ValueError(f"Deployment '{deployment_id}' is not configured.")
        if not dep.enabled:
            raise ValueError(f"Deployment '{deployment_id}' is disabled.")
        return self._resolve_from_def(dep)

    def resolve_deployment_for_capability(
        self,
        capability: str,
        requested: str | None = None,
        *,
        fallback_to_default_chat: bool = True,
    ) -> ResolvedDeployment:
        cap = (capability or "").strip().lower()
        requested = (requested or "").strip()

        if requested:
            if requested in self.deployments:
                resolved = self.get_deployment(requested)
                if cap and not self.has_capability(resolved, cap):
                    raise ValueError(
                        f"Deployment '{requested}' does not support required capability '{cap}'."
                    )
                return resolved

            if not fallback_to_default_chat:
                raise ValueError(
                    f"Requested deployment '{requested}' was not found and fallback is disabled."
                )

        if cap:
            for dep_id, dep in self.deployments.items():
                if not dep.enabled:
                    continue
                if not self.has_capability(dep, cap):
                    continue
                provider = self.providers.get(dep.provider)
                if not provider or not provider.enabled:
                    continue

                if dep_id == requested:
                    return self._resolve_from_def(dep)

            if requested and fallback_to_default_chat:
                default_chat = self.resolve_chat_target(None)
                if self.has_capability(default_chat, cap):
                    return default_chat

            raise ValueError(f"No enabled deployment supports required capability '{cap}'.")

        if requested:
            return self.resolve_chat_target(requested)

        return self.resolve_chat_target(None)

    def resolve_chat_target(self, requested: str | None) -> ResolvedDeployment:
        requested = (requested or "").strip()

        if not requested:
            requested = self.get_default_chat_deployment_id()

        if requested in self.deployments:
            resolved = self.get_deployment(requested)
            if not self.has_capability(resolved, "chat"):
                raise ValueError(f"Deployment '{requested}' does not support chat.")
            return resolved

        # Backward-compatibility path:
        # treat unknown requested value as a raw model string on the default chat provider.
        default_id = self.get_default_chat_deployment_id()
        default_dep = self.deployments[default_id]
        provider = self.providers.get(default_dep.provider)
        if not provider:
            raise ValueError(f"Default provider '{default_dep.provider}' is not configured.")
        if not provider.enabled:
            raise ValueError(f"Default provider '{provider.id}' is disabled.")

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
            raise ValueError(
                f"No chat provider factory registered for provider type '{deployment.provider_type}'."
            )
        provider_def = self.providers[deployment.provider_id]
        return factory(provider_def)

    def get_catalog_provider(self, provider_id: str) -> ModelCatalogProvider:
        provider_def = self.providers.get(provider_id)
        if not provider_def:
            raise ValueError(f"Provider '{provider_id}' is not configured.")
        factory = self.catalog_factories.get(provider_def.type)
        if not factory:
            raise ValueError(
                f"No catalog provider factory registered for provider type '{provider_def.type}'."
            )
        return factory(provider_def)
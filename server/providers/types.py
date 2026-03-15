from dataclasses import dataclass, field
from typing import Any


ModelCatalog = dict[str, dict[str, Any]]
ModelInput = list[dict[str, Any]]


@dataclass(frozen=True)
class ProviderDef:
    id: str
    type: str
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class DeploymentDef:
    id: str
    provider: str
    model: str
    display_name: str = ""
    capabilities: tuple[str, ...] = ()
    enabled: bool = True
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedDeployment:
    id: str
    provider_id: str
    provider_type: str
    model: str
    display_name: str
    capabilities: tuple[str, ...]
    tags: tuple[str, ...] = ()
    enabled: bool = True
    base_url: str = ""

@dataclass
class ProviderErrorInfo:
    provider_id: str
    deployment_id: str | None
    model: str | None
    message: str
    status_code: int | None = None
    request_id: str | None = None
    provider_error_type: str | None = None
    recovery_step: str | None = None
    raw: Any = None


@dataclass
class ChatResult:
    text: str
    provider_id: str
    deployment_id: str | None
    model: str
    raw: Any = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider_id: str
    provider_type: str
    vendor: str
    display_name: str
    description: str = ""
    created: int | None = None
    owned_by: str | None = None
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    context_window: int | None = None
    tags: tuple[str, ...] = ()

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Optional

from callie_logging import setup_logging
from env_utils_new import redact_config_value

log, _log_settings = setup_logging("provider_backends")


OPENAI_API_BACKEND = "openai_api"
SUPPORTED_BACKENDS = {OPENAI_API_BACKEND, "authenticated_session"}


@dataclass(frozen=True)
class ConnectorProviderConfig:
    backend: str = OPENAI_API_BACKEND
    auth_mode: str = "api_key"
    oauth_token: str = ""
    oauth_refresh_token: str = ""
    token_path: str = ""
    refresh_token_path: str = ""
    oauth_device_code_command: str = ""

    @property
    def is_openai_api(self) -> bool:
        return self.backend == OPENAI_API_BACKEND


def normalize_provider_backend(raw: Optional[str]) -> str:
    backend = (raw or OPENAI_API_BACKEND).strip().lower().replace("-", "_")
    aliases = {
        "openai": OPENAI_API_BACKEND,
        "openai_responses": OPENAI_API_BACKEND,
        "api": OPENAI_API_BACKEND,
        "api_key": OPENAI_API_BACKEND,
        "oauth": "authenticated_session",
        "session": "authenticated_session",
        "codex_oauth": "authenticated_session",
    }
    return aliases.get(backend, backend)


def validate_provider_config(cfg: ConnectorProviderConfig) -> None:
    if cfg.backend not in SUPPORTED_BACKENDS:
        raise RuntimeError(
            f"Unsupported CONNECTOR_LLM_BACKEND={cfg.backend!r}. "
            f"Supported values: {', '.join(sorted(SUPPORTED_BACKENDS))}"
        )
    if cfg.is_openai_api:
        return
    log.info(
        "Connector LLM backend %s selected with auth_mode=%s oauth_token=%s token_path=%s refresh_token_path=%s. "
        "Authenticated-session transport enabled.",
        cfg.backend,
        cfg.auth_mode,
        redact_config_value("OPENAI_OAUTH_TOKEN", cfg.oauth_token),
        redact_config_value("OPENAI_OAUTH_TOKEN_PATH", cfg.token_path),
        redact_config_value("OPENAI_OAUTH_REFRESH_TOKEN_PATH", cfg.refresh_token_path),
    )


@dataclass(frozen=True)
class OAuthTokenBundle:
    access_token: str = ""
    refresh_token: str = ""
    access_source: str = "missing"
    refresh_source: str = "missing"

    @property
    def has_access(self) -> bool:
        return bool(self.access_token.strip())

    @property
    def has_refresh(self) -> bool:
        return bool(self.refresh_token.strip())


def _read_secret_file(path: str) -> str:
    if not path:
        return ""
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def resolve_oauth_tokens(cfg: ConnectorProviderConfig) -> OAuthTokenBundle:
    access_direct = (cfg.oauth_token or "").strip()
    refresh_direct = (cfg.oauth_refresh_token or "").strip()
    if access_direct:
        access_token = access_direct
        access_source = "env:OPENAI_OAUTH_TOKEN"
    else:
        access_token = _read_secret_file(cfg.token_path)
        access_source = "file:OPENAI_OAUTH_TOKEN_PATH" if access_token else "missing"

    if refresh_direct:
        refresh_token = refresh_direct
        refresh_source = "env:OPENAI_OAUTH_REFRESH_TOKEN"
    else:
        refresh_token = _read_secret_file(cfg.refresh_token_path)
        refresh_source = "file:OPENAI_OAUTH_REFRESH_TOKEN_PATH" if refresh_token else "missing"

    return OAuthTokenBundle(
        access_token=access_token,
        refresh_token=refresh_token,
        access_source=access_source,
        refresh_source=refresh_source,
    )

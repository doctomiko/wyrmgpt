from __future__ import annotations

from dataclasses import dataclass
import socket
from typing import Optional

import aiohttp
import discord
import httpx


@dataclass(frozen=True)
class ServiceOutage:
    service: str
    kind: str
    admin_detail: str
    user_message: str
    retryable: bool = True


def _status_from_httpx(exc: Exception) -> Optional[int]:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def classify_openai_exception(exc: Exception) -> Optional[ServiceOutage]:
    status = _status_from_httpx(exc)
    if status == 429:
        return ServiceOutage(
            service="OpenAI",
            kind="rate_limit_or_quota",
            admin_detail="OpenAI returned HTTP 429. This is rate limit, quota, or capacity pressure.",
            user_message="Oops, looks like OpenAI is rate-limiting us right now. Let's try again later.",
        )
    if status is not None and 500 <= status <= 599:
        return ServiceOutage(
            service="OpenAI",
            kind="upstream_5xx",
            admin_detail=f"OpenAI returned HTTP {status}. Upstream service is unavailable or degraded.",
            user_message="Oops, looks like OpenAI is not responding right now. Let's try again later.",
        )
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError, socket.gaierror)):
        return ServiceOutage(
            service="OpenAI",
            kind="network_or_dns",
            admin_detail=f"OpenAI request failed before a usable response: {type(exc).__name__}.",
            user_message="Oops, looks like OpenAI is not reachable right now. Let's try again later.",
        )
    return None


def classify_discord_exception(exc: Exception) -> Optional[ServiceOutage]:
    if isinstance(exc, (aiohttp.ClientConnectorDNSError, socket.gaierror)):
        return ServiceOutage(
            service="Discord",
            kind="dns",
            admin_detail=f"Discord DNS resolution failed: {type(exc).__name__}.",
            user_message="Oops, looks like Discord is not reachable right now. Let's try again later.",
        )
    if isinstance(exc, (aiohttp.ClientConnectorError, TimeoutError, OSError)):
        return ServiceOutage(
            service="Discord",
            kind="network",
            admin_detail=f"Discord network connection failed: {type(exc).__name__}.",
            user_message="Oops, looks like Discord is not responding right now. Let's try again later.",
        )
    if isinstance(exc, discord.HTTPException):
        status = getattr(exc, "status", None)
        if status == 429:
            return ServiceOutage(
                service="Discord",
                kind="rate_limit",
                admin_detail="Discord returned HTTP 429 while sending.",
                user_message="Oops, looks like Discord is rate-limiting us right now. Let's try again later.",
            )
        if isinstance(status, int) and 500 <= status <= 599:
            return ServiceOutage(
                service="Discord",
                kind="upstream_5xx",
                admin_detail=f"Discord returned HTTP {status} while sending.",
                user_message="Oops, looks like Discord is not responding right now. Let's try again later.",
            )
    return None


def format_admin_outage(outage: ServiceOutage, *, context: str = "") -> str:
    prefix = f"{outage.service} outage kind={outage.kind}"
    if context:
        prefix += f" context={context}"
    return f"{prefix}: {outage.admin_detail}"

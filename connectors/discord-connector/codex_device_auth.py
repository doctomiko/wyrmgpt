from __future__ import annotations

import argparse
import asyncio
import os
import sys
import re
import time
from typing import Any, Dict

import httpx
from dotenv import load_dotenv


OPENAI_AUTH_BASE_URL = "https://auth.openai.com"
OPENAI_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_CODEX_DEVICE_CALLBACK_URL = f"{OPENAI_AUTH_BASE_URL}/deviceauth/callback"
DEFAULT_ACCESS_TOKEN_PATH = "/runtime/config/openai_oauth_token"
DEFAULT_REFRESH_TOKEN_PATH = "/runtime/config/openai_oauth_refresh_token"
DEFAULT_TIMEOUT_SECONDS = 15 * 60
DEFAULT_POLL_INTERVAL_SECONDS = 5


def _json_obj(response: httpx.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _write_secret(path: str, value: str) -> None:
    if not path:
        raise RuntimeError("Token output path is empty.")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value.strip() + "\n")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _headers(content_type: str) -> Dict[str, str]:
    return {
        "Content-Type": content_type,
        "originator": "wyrmgpt-discord-connector",
        "User-Agent": "wyrmgpt-discord-connector",
    }


def _sanitize_error_body(text: str) -> str:
    text = re.sub(r"(?i)(access_token|refresh_token|id_token)[^,}\n]*", r"\1=<redacted>", text)
    return " ".join(text.split())[:1000]


async def _request_user_code(client: httpx.AsyncClient) -> Dict[str, Any]:
    response = await client.post(
        f"{OPENAI_AUTH_BASE_URL}/api/accounts/deviceauth/usercode",
        headers=_headers("application/json"),
        json={"client_id": OPENAI_CODEX_CLIENT_ID},
    )
    if response.status_code == 404:
        raise RuntimeError("OpenAI Codex device-code login is not enabled for this account/server.")
    response.raise_for_status()
    data = _json_obj(response)
    device_auth_id = str(data.get("device_auth_id") or "").strip()
    user_code = str(data.get("user_code") or data.get("usercode") or "").strip()
    if not device_auth_id or not user_code:
        raise RuntimeError("OpenAI device-code response did not include device_auth_id and user_code.")
    return {
        "device_auth_id": device_auth_id,
        "user_code": user_code,
        "verification_url": f"{OPENAI_AUTH_BASE_URL}/codex/device",
        "interval": int(data.get("interval") or DEFAULT_POLL_INTERVAL_SECONDS),
    }


async def _poll_authorization_code(
    client: httpx.AsyncClient,
    *,
    device_auth_id: str,
    user_code: str,
    interval: int,
    timeout_seconds: int,
) -> Dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = await client.post(
            f"{OPENAI_AUTH_BASE_URL}/api/accounts/deviceauth/token",
            headers=_headers("application/json"),
            json={"device_auth_id": device_auth_id, "user_code": user_code},
        )
        if response.status_code == 200:
            data = _json_obj(response)
            authorization_code = str(data.get("authorization_code") or "").strip()
            code_verifier = str(data.get("code_verifier") or "").strip()
            if not authorization_code or not code_verifier:
                raise RuntimeError("OpenAI authorization response did not include exchange fields.")
            return {
                "authorization_code": authorization_code,
                "code_verifier": code_verifier,
            }
        if response.status_code not in {403, 404}:
            response.raise_for_status()
        await asyncio.sleep(max(1, interval))
    raise TimeoutError("OpenAI device authorization timed out.")


async def _exchange_tokens(
    client: httpx.AsyncClient,
    *,
    authorization_code: str,
    code_verifier: str,
) -> Dict[str, str]:
    response = await client.post(
        f"{OPENAI_AUTH_BASE_URL}/oauth/token",
        headers=_headers("application/x-www-form-urlencoded"),
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": OPENAI_CODEX_DEVICE_CALLBACK_URL,
            "client_id": OPENAI_CODEX_CLIENT_ID,
            "code_verifier": code_verifier,
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(
            "OpenAI token exchange failed: "
            f"HTTP {response.status_code} {_sanitize_error_body(response.text)}"
        )
    data = _json_obj(response)
    access_token = str(data.get("access_token") or "").strip()
    refresh_token = str(data.get("refresh_token") or "").strip()
    if not access_token or not refresh_token:
        raise RuntimeError("OpenAI token exchange succeeded but did not return access and refresh tokens.")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


async def run(args: argparse.Namespace) -> int:
    if args.env_file:
        load_dotenv(args.env_file)

    access_path = args.access_token_path or os.getenv("OPENAI_OAUTH_TOKEN_PATH") or DEFAULT_ACCESS_TOKEN_PATH
    refresh_path = (
        args.refresh_token_path
        or os.getenv("OPENAI_OAUTH_REFRESH_TOKEN_PATH")
        or DEFAULT_REFRESH_TOKEN_PATH
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        device = await _request_user_code(client)
        print("OpenAI Codex device authorization")
        print(f"Go to: {device['verification_url']}")
        print(f"Enter code: {device['user_code']}")
        print(f"Expires in about {args.timeout_seconds // 60} minutes. Waiting for completion...")
        sys.stdout.flush()

        authorization = await _poll_authorization_code(
            client,
            device_auth_id=device["device_auth_id"],
            user_code=device["user_code"],
            interval=device["interval"],
            timeout_seconds=args.timeout_seconds,
        )
        tokens = await _exchange_tokens(client, **authorization)

    _write_secret(access_path, tokens["access_token"])
    _write_secret(refresh_path, tokens["refresh_token"])
    print(f"Wrote access token: {access_path}")
    print(f"Wrote refresh token: {refresh_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OpenAI/Codex device auth and store OAuth token files.")
    parser.add_argument("--env-file", default=os.getenv("CONNECTOR_ENV_FILE", ""))
    parser.add_argument("--access-token-path", default="")
    parser.add_argument("--refresh-token-path", default="")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run(parse_args())))
    except KeyboardInterrupt:
        raise SystemExit(130)

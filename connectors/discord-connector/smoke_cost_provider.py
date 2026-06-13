from __future__ import annotations

import os
import base64
import json
import tempfile

from codex_transport import (
    _codex_payload,
    _extract_text_from_events,
    _unsupported_parameter_from_message,
    extract_codex_account_id,
)
from cost_tracking import CostTelemetryConfig, calculate_usage_cost, format_cost_log, usage_cost_to_dict
from provider_backends import (
    ConnectorProviderConfig,
    normalize_provider_backend,
    resolve_oauth_tokens,
    validate_provider_config,
)


def main() -> None:
    data = {
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 250,
            "total_tokens": 1250,
        }
    }
    cfg = CostTelemetryConfig(
        enabled=True,
        monthly_budget_usd=25.0,
        default_input_per_1m=0.15,
        default_output_per_1m=0.60,
    )
    cost = calculate_usage_cost(data, "gpt-4o-mini", cfg)
    assert cost.input_tokens == 1000
    assert cost.output_tokens == 250
    assert cost.total_tokens == 1250
    assert cost.estimated_cost_usd is not None and cost.estimated_cost_usd > 0
    rendered = format_cost_log(cost)
    assert "cost_estimate_usd=" in rendered
    assert "budget_used_pct=" in rendered
    diag = usage_cost_to_dict(cost)
    assert diag["input_tokens"] == 1000
    assert diag["budget_used_pct"] is not None

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
        f.write('{"gpt-test":{"input_cost_per_million":2.0,"output_cost_per_million":8.0}}')
        pricing_path = f.name
    try:
        file_cfg = CostTelemetryConfig(enabled=True, model_pricing_json=pricing_path)
        file_cost = calculate_usage_cost(data, "gpt-test", file_cfg)
        assert file_cost.estimated_cost_usd is not None and file_cost.estimated_cost_usd > cost.estimated_cost_usd
        assert file_cost.pricing_source.endswith(":gpt-test")
    finally:
        os.unlink(pricing_path)

    assert normalize_provider_backend("openai") == "openai_api"
    assert normalize_provider_backend("codex-oauth") == "authenticated_session"
    validate_provider_config(ConnectorProviderConfig(backend="openai_api"))

    direct_tokens = resolve_oauth_tokens(
        ConnectorProviderConfig(
            oauth_token="access-direct",
            oauth_refresh_token="refresh-direct",
        )
    )
    assert direct_tokens.access_token == "access-direct"
    assert direct_tokens.refresh_token == "refresh-direct"
    assert direct_tokens.access_source == "env:OPENAI_OAUTH_TOKEN"
    assert direct_tokens.refresh_source == "env:OPENAI_OAUTH_REFRESH_TOKEN"

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as access_file:
        access_file.write("access-file\n")
        access_path = access_file.name
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as refresh_file:
        refresh_file.write("refresh-file\n")
        refresh_path = refresh_file.name
    try:
        file_tokens = resolve_oauth_tokens(
            ConnectorProviderConfig(
                token_path=access_path,
                refresh_token_path=refresh_path,
            )
        )
        assert file_tokens.access_token == "access-file"
        assert file_tokens.refresh_token == "refresh-file"
        assert file_tokens.access_source == "file:OPENAI_OAUTH_TOKEN_PATH"
        assert file_tokens.refresh_source == "file:OPENAI_OAUTH_REFRESH_TOKEN_PATH"
    finally:
        os.unlink(access_path)
        os.unlink(refresh_path)

    validate_provider_config(
        ConnectorProviderConfig(
            backend="authenticated_session",
            auth_mode="oauth_device_code",
            oauth_token="secret-test-token",
        )
    )

    jwt_payload = {
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "acct-test",
        }
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(jwt_payload).encode("utf-8")).decode("ascii").rstrip("=")
    assert extract_codex_account_id(f"header.{payload_b64}.signature") == "acct-test"

    text, final = _extract_text_from_events(
        [
            {"type": "response.output_text.delta", "delta": "hello "},
            {"type": "response.output_text.delta", "delta": "world"},
            {"type": "response.completed", "response": {"id": "resp-test", "status": "completed"}},
        ]
    )
    assert text == "hello world"
    assert final["id"] == "resp-test"
    assert _unsupported_parameter_from_message('{"detail":"Unsupported parameter: max_output_tokens"}') == "max_output_tokens"
    payload = _codex_payload({"model": "gpt-5.5", "max_output_tokens": 100, "stream": True})
    assert "max_output_tokens" not in payload
    assert payload["model"] == "gpt-5.5"

    print("cost/provider smoke ok")


if __name__ == "__main__":
    main()

import re
from typing import Any, Iterator, cast

from openai import OpenAI, APIStatusError
from openai.types.responses import ResponseInputParam

from .types import (
    ChatResult,
    ModelInfo,
    ModelCatalog,
    ModelInput,
    ProviderDef,
    ResolvedDeployment,
)


class ProviderExecutionError(Exception):
    def __init__(self, message: str, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.payload = payload or {}


def _effective_api_key(provider_def: ProviderDef) -> str | None:
    raw = (provider_def.api_key or "").strip()
    if raw:
        return raw
    if provider_def.type in ("ollama", "lmstudio", "openai_compat"):
        return "local-not-needed"
    return None


def _default_vendor(provider_def: ProviderDef) -> str:
    if provider_def.type == "openai":
        return "OpenAI"
    if provider_def.type == "ollama":
        return "Ollama"
    if provider_def.type == "lmstudio":
        return "LM Studio"
    return provider_def.id


def extract_output_text(resp) -> str:
    t = getattr(resp, "output_text", None)
    if isinstance(t, str) and t.strip():
        return t.strip()

    out = getattr(resp, "output", None)
    if isinstance(out, list):
        chunks = []
        for item in out:
            content = getattr(item, "content", None)
            if isinstance(content, list):
                for c in content:
                    if getattr(c, "type", None) == "output_text":
                        chunks.append(getattr(c, "text", ""))
        joined = "".join(chunks).strip()
        if joined:
            return joined

    return ""


def openai_error_payload(e: APIStatusError) -> dict[str, Any]:
    status = getattr(e, "status_code", None)
    req_id = None
    err_json = None

    try:
        err_json = e.response.json()
        req_id = err_json.get("error", {}).get("request_id") or err_json.get("request_id")
    except Exception:
        try:
            err_json = {"raw": e.response.text}
        except Exception:
            err_json = {"raw": repr(getattr(e, "response", None))}

    return {
        "status_code": status,
        "request_id": req_id,
        "body": err_json,
        "provider_error_type": type(e).__name__,
    }


def extract_error_message(payload: dict[str, Any]) -> str:
    body = payload.get("body") or {}
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return err.get("message") or body.get("message") or "API error"
        return body.get("message") or "API error"
    return "API error"


def _unsupported_parameter_name(payload: dict[str, Any]) -> str | None:
    msg = extract_error_message(payload)
    if not msg:
        return None
    m = re.search(r"Unsupported parameter:\s*[\"']([^\"']+)[\"']", msg)
    if m:
        return (m.group(1) or "").strip() or None
    return None


def _drop_nested_option(options: dict[str, Any], dotted_name: str) -> tuple[dict[str, Any], bool]:
    if not dotted_name:
        return dict(options), False

    out = dict(options)
    parts = [p for p in str(dotted_name).split('.') if p]
    if not parts:
        return out, False

    if len(parts) == 1:
        key = parts[0]
        if key in out:
            out.pop(key, None)
            return out, True
        return out, False

    head = parts[0]
    cur = out.get(head)
    if not isinstance(cur, dict):
        return out, False

    cur_copy = dict(cur)
    node = cur_copy
    changed = False
    for part in parts[1:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            return out, False
        child_copy = dict(child)
        node[part] = child_copy
        node = child_copy
    leaf = parts[-1]
    if leaf in node:
        node.pop(leaf, None)
        changed = True

    if changed:
        if cur_copy:
            out[head] = cur_copy
        else:
            out.pop(head, None)
    return out, changed


def _maybe_retryable_options_from_error(options: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    name = _unsupported_parameter_name(payload)
    if not name:
        return dict(options), None
    stripped, changed = _drop_nested_option(options, name)
    return stripped, (name if changed else None)


class OpenAIProvider:
    def __init__(self, provider_def: ProviderDef, model_catalog: ModelCatalog | None = None):
        kwargs: dict[str, Any] = {}

        api_key = _effective_api_key(provider_def)
        if api_key:
            kwargs["api_key"] = api_key
        if provider_def.base_url:
            kwargs["base_url"] = provider_def.base_url

        self.client = OpenAI(**kwargs)
        self.provider_def = provider_def
        self.model_catalog = model_catalog or {}

    def complete(
        self,
        deployment: ResolvedDeployment,
        model_input: ModelInput,
        request_options: dict[str, Any] | None = None,
    ) -> ChatResult:
        kwargs: dict[str, Any] = dict(request_options or {})
        retried_without: list[str] = []
        for _attempt in range(2):
            try:
                resp = self.client.responses.create(
                    model=deployment.model,
                    input=cast(ResponseInputParam, model_input),
                    **kwargs,
                )
                text = extract_output_text(resp)
                return ChatResult(
                    text=text,
                    provider_id=deployment.provider_id,
                    deployment_id=deployment.id,
                    model=deployment.model,
                    raw=resp,
                    warnings=[f"Dropped unsupported parameter: {name}" for name in retried_without],
                )
            except APIStatusError as e:
                payload = openai_error_payload(e)
                stripped_kwargs, stripped_name = _maybe_retryable_options_from_error(kwargs, payload)
                if stripped_name and stripped_kwargs != kwargs:
                    kwargs = stripped_kwargs
                    retried_without.append(stripped_name)
                    continue
                raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e

    def stream_text(
        self,
        deployment: ResolvedDeployment,
        model_input: ModelInput,
        request_options: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        kwargs: dict[str, Any] = dict(request_options or {})
        saw_stream_item = False
        for _attempt in range(2):
            try:
                with self.client.responses.stream(
                    model=deployment.model,
                    input=cast(ResponseInputParam, model_input),
                    **kwargs,
                ) as stream:
                    for event in stream:
                        saw_stream_item = True
                        if event.type == "response.output_text.delta":
                            yield event.delta
                        elif event.type == "response.refusal.delta":
                            yield event.delta
                        elif event.type == "response.reasoning_summary_text.delta":
                            yield {
                                "type": "reasoning_delta",
                                "delta": getattr(event, "delta", "") or "",
                                "summary_index": getattr(event, "summary_index", None),
                                "item_id": getattr(event, "item_id", None),
                            }
                        elif event.type == "response.reasoning_summary_text.done":
                            yield {
                                "type": "reasoning_done",
                                "text": getattr(event, "text", "") or "",
                                "summary_index": getattr(event, "summary_index", None),
                                "item_id": getattr(event, "item_id", None),
                            }
                        elif event.type == "response.error":
                            yield "\n[error]\n"
                return
            except APIStatusError as e:
                payload = openai_error_payload(e)
                stripped_kwargs, stripped_name = _maybe_retryable_options_from_error(kwargs, payload)
                if (not saw_stream_item) and stripped_name and stripped_kwargs != kwargs:
                    kwargs = stripped_kwargs
                    continue
                raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e

    def list_models(self, provider: ProviderDef) -> list[ModelInfo]:
        out: list[ModelInfo] = []

        model_objs = self.client.models.list()
        for m in model_objs:
            mid = getattr(m, "id", None)
            if not mid:
                continue

            meta = self.model_catalog.get(mid, {})
            out.append(
                ModelInfo(
                    id=mid,
                    provider_id=provider.id,
                    provider_type=provider.type,
                    vendor=meta.get("vendor", _default_vendor(provider)),                    
                    #vendor=meta.get("vendor", "OpenAI"),
                    display_name=meta.get("display_name", mid),
                    description=meta.get("description", ""),
                    created=getattr(m, "created", None),
                    owned_by=getattr(m, "owned_by", None),
                    input_cost_per_million=meta.get("input_cost_per_million"),
                    output_cost_per_million=meta.get("output_cost_per_million"),
                    context_window=meta.get("context_window"),
                    tags=tuple(meta.get("tags", [])),
                )
            )

        return out

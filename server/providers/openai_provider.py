import re
from typing import Any, Iterator, cast

from openai import OpenAI, APIStatusError

from server.logging_helper import log_debug, log_info, log_warn
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


def _iter_reasoning_texts_from_item(item) -> Iterator[str]:
    if item is None:
        return
    summary = getattr(item, "summary", None)
    if summary is None and isinstance(item, dict):
        summary = item.get("summary")
    if isinstance(summary, list):
        for part in summary:
            part_text = getattr(part, "text", None)
            if part_text is None and isinstance(part, dict):
                part_text = part.get("text")
            if part_text:
                yield str(part_text)
    content = getattr(item, "content", None)
    if content is None and isinstance(item, dict):
        content = item.get("content")
    if isinstance(content, list):
        for part in content:
            part_type = getattr(part, "type", None)
            if part_type is None and isinstance(part, dict):
                part_type = part.get("type")
            if str(part_type or "") != "reasoning_text":
                continue
            part_text = getattr(part, "text", None)
            if part_text is None and isinstance(part, dict):
                part_text = part.get("text")
            if part_text:
                yield str(part_text)


def _iter_reasoning_texts_from_response(resp) -> Iterator[str]:
    if resp is None:
        return
    output = getattr(resp, "output", None)
    if output is None and isinstance(resp, dict):
        output = resp.get("output")
    if not isinstance(output, list):
        return
    seen: set[str] = set()
    for item in output:
        for text in _iter_reasoning_texts_from_item(item):
            cleaned = str(text or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            yield cleaned


def _get_stream_final_response(stream) -> Any | None:
    getter = getattr(stream, "get_final_response", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    for attr in ("final_response", "response", "current_response_snapshot"):
        value = getattr(stream, attr, None)
        if value is not None:
            return value
    return None


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
        for attempt in range(2):
            try:
                log_info('Provider request start provider=%s deployment=%s model=%s mode=complete attempt=%s options=%s', deployment.provider_id, deployment.id, deployment.model, attempt + 1, sorted(kwargs.keys()))
                print(f"[provider.start] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete attempt={attempt + 1} options={sorted(kwargs.keys())}", flush=True)
                resp = self.client.responses.create(
                    model=deployment.model,
                    input=cast(ResponseInputParam, model_input),
                    **kwargs,
                )
                text = extract_output_text(resp)
                log_info('Provider response done provider=%s deployment=%s model=%s mode=complete chars=%s warnings=%s', deployment.provider_id, deployment.id, deployment.model, len(text or ''), retried_without)
                print(f"[provider.done] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete chars={len(text or '')} warnings={retried_without}", flush=True)
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
                    log_warn('Provider request retry provider=%s deployment=%s model=%s dropped=%s', deployment.provider_id, deployment.id, deployment.model, stripped_name)
                    print(f"[provider.retry] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} dropped={stripped_name}", flush=True)
                    continue
                log_warn('Provider request failed provider=%s deployment=%s model=%s mode=complete status=%s message=%s', deployment.provider_id, deployment.id, deployment.model, payload.get('status_code'), extract_error_message(payload))
                print(f"[provider.error] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete status={payload.get('status_code')} message={extract_error_message(payload)}", flush=True)
                raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e

    def stream_text(
        self,
        deployment: ResolvedDeployment,
        model_input: ModelInput,
        request_options: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        kwargs: dict[str, Any] = dict(request_options or {})
        saw_stream_item = False
        for attempt in range(2):
            reasoning_event_count = 0
            text_delta_count = 0
            first_reasoning_logged = False
            try:
                log_info('Provider request start provider=%s deployment=%s model=%s mode=stream attempt=%s options=%s', deployment.provider_id, deployment.id, deployment.model, attempt + 1, sorted(kwargs.keys()))
                print(f"[provider.start] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream attempt={attempt + 1} options={sorted(kwargs.keys())}", flush=True)
                with self.client.responses.stream(
                    model=deployment.model,
                    input=cast(ResponseInputParam, model_input),
                    **kwargs,
                ) as stream:
                    final_response = None
                    for event in stream:
                        saw_stream_item = True
                        event_type = getattr(event, 'type', '') or ''
                        if event_type == "response.output_text.delta":
                            delta = getattr(event, 'delta', '') or ''
                            if delta:
                                text_delta_count += 1
                                yield delta
                        elif event_type == "response.refusal.delta":
                            delta = getattr(event, 'delta', '') or ''
                            if delta:
                                yield delta
                        elif event_type == "response.completed":
                            final_response = getattr(event, 'response', None) or final_response
                        elif event_type in {
                            'response.reasoning_summary_text.delta',
                            'response.reasoning_summary_text.done',
                            'response.reasoning_summary_part.added',
                            'response.reasoning_summary_part.done',
                            'response.reasoning_text.delta',
                            'response.reasoning_text.done',
                        } or str(event_type).startswith('response.reasoning'):
                            reasoning_event_count += 1
                            part = getattr(event, 'part', None)
                            part_text = ''
                            part_type = ''
                            if part is not None:
                                part_text = getattr(part, 'text', None) or (part.get('text') if isinstance(part, dict) else '') or ''
                                part_type = getattr(part, 'type', None) or (part.get('type') if isinstance(part, dict) else '') or ''
                            delta_text = getattr(event, 'delta', None) or ''
                            done_text = getattr(event, 'text', None) or ''
                            if not first_reasoning_logged:
                                first_reasoning_logged = True
                                log_info('Provider reasoning stream detected provider=%s deployment=%s model=%s event=%s', deployment.provider_id, deployment.id, deployment.model, event_type)
                                print(f"[provider.reasoning] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} event={event_type}", flush=True)
                            log_debug('Provider stream event provider=%s deployment=%s model=%s event=%s', deployment.provider_id, deployment.id, deployment.model, event_type)
                            yield {
                                'type': 'reasoning_done' if event_type.endswith('.done') else 'reasoning_delta',
                                'delta': delta_text,
                                'text': done_text,
                                'part_text': part_text,
                                'part_type': part_type,
                                'summary_index': getattr(event, 'summary_index', None),
                                'item_id': getattr(event, 'item_id', None),
                                'event_type': event_type,
                            }
                        elif event_type == "response.error":
                            yield "\n[error]\n"
                    if reasoning_event_count == 0:
                        final_response = final_response or _get_stream_final_response(stream)
                        fallback_texts = list(_iter_reasoning_texts_from_response(final_response))
                        if fallback_texts:
                            for text_value in fallback_texts:
                                reasoning_event_count += 1
                                if not first_reasoning_logged:
                                    first_reasoning_logged = True
                                    log_info('Provider reasoning fallback detected provider=%s deployment=%s model=%s', deployment.provider_id, deployment.id, deployment.model)
                                    print(f"[provider.reasoning] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} event=fallback.final_response", flush=True)
                                yield {
                                    'type': 'reasoning_done',
                                    'delta': '',
                                    'text': text_value,
                                    'part_text': '',
                                    'part_type': 'summary_text',
                                    'summary_index': None,
                                    'item_id': None,
                                    'event_type': 'response.reasoning.fallback',
                                }
                log_info('Provider response done provider=%s deployment=%s model=%s mode=stream text_deltas=%s reasoning_events=%s', deployment.provider_id, deployment.id, deployment.model, text_delta_count, reasoning_event_count)
                print(f"[provider.done] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream text_deltas={text_delta_count} reasoning_events={reasoning_event_count}", flush=True)
                return
            except APIStatusError as e:
                payload = openai_error_payload(e)
                stripped_kwargs, stripped_name = _maybe_retryable_options_from_error(kwargs, payload)
                if (not saw_stream_item) and stripped_name and stripped_kwargs != kwargs:
                    kwargs = stripped_kwargs
                    log_warn('Provider stream retry provider=%s deployment=%s model=%s dropped=%s', deployment.provider_id, deployment.id, deployment.model, stripped_name)
                    print(f"[provider.retry] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} dropped={stripped_name}", flush=True)
                    continue
                log_warn('Provider request failed provider=%s deployment=%s model=%s mode=stream status=%s message=%s', deployment.provider_id, deployment.id, deployment.model, payload.get('status_code'), extract_error_message(payload))
                print(f"[provider.error] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream status={payload.get('status_code')} message={extract_error_message(payload)}", flush=True)
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

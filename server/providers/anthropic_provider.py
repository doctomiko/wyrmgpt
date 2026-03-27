from __future__ import annotations

from typing import Any, Iterator

from anthropic import APIStatusError, Anthropic

from server.logging_helper import log_info, log_warn
from .message_transforms import to_anthropic_messages
from .openai_provider import ProviderExecutionError, extract_error_message
from .types import ChatResult, ModelCatalog, ModelInfo, ModelInput, ProviderDef, ResolvedDeployment


_DEFAULT_MAX_TOKENS = 4096


def anthropic_error_payload(e: APIStatusError) -> dict[str, Any]:
    status = getattr(e, 'status_code', None)
    req_id = getattr(e, 'request_id', None)
    body: Any = None

    err_body = getattr(e, 'body', None)
    if err_body is not None:
        body = err_body
    else:
        body = {'message': str(e)}

    if req_id is None:
        response = getattr(e, 'response', None)
        headers = getattr(response, 'headers', None)
        if headers is not None:
            try:
                req_id = headers.get('request-id') or headers.get('x-request-id')
            except Exception:
                req_id = None

    return {
        'status_code': status,
        'request_id': req_id,
        'body': body,
        'provider_error_type': type(e).__name__,
    }


def anthropic_generic_error_payload(e: Exception) -> dict[str, Any]:
    return {
        'status_code': None,
        'request_id': None,
        'body': {'message': str(e) or repr(e)},
        'provider_error_type': type(e).__name__,
    }


def _event_get(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            cur = getattr(cur, key, None)
    return cur


class AnthropicProvider:
    def __init__(self, provider_def: ProviderDef, model_catalog: ModelCatalog | None = None):
        kwargs: dict[str, Any] = {}
        api_key = (provider_def.api_key or '').strip()
        if api_key:
            kwargs['api_key'] = api_key
        self.client = Anthropic(**kwargs)
        self.provider_def = provider_def
        self.model_catalog = model_catalog or {}

    def _request_kwargs(
        self,
        deployment: ResolvedDeployment,
        model_input: ModelInput,
        request_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_text, messages = to_anthropic_messages(model_input)
        options = dict(request_options or {})
        max_tokens = options.pop('max_output_tokens', None)
        if max_tokens is None:
            max_tokens = options.pop('max_tokens', None)
        kwargs: dict[str, Any] = {
            'model': deployment.model,
            'messages': messages,
            'max_tokens': max(1, int(max_tokens or _DEFAULT_MAX_TOKENS)),
        }
        if system_text:
            kwargs['system'] = system_text
        for key in ('temperature', 'top_p', 'top_k', 'stop_sequences', 'metadata', 'thinking', 'output_config'):
            if key in options and options[key] is not None:
                kwargs[key] = options[key]
        return kwargs

    def _extract_text(self, resp: Any) -> str:
        parts = []
        for block in getattr(resp, 'content', None) or []:
            if getattr(block, 'type', None) == 'text':
                text = getattr(block, 'text', None)
                if isinstance(text, str) and text:
                    parts.append(text)
        return ''.join(parts).strip()

    def complete(
        self,
        deployment: ResolvedDeployment,
        model_input: ModelInput,
        request_options: dict[str, Any] | None = None,
    ) -> ChatResult:
        try:
            kwargs = self._request_kwargs(deployment, model_input, request_options)
            log_info('Provider request start provider=%s deployment=%s model=%s mode=complete options=%s', deployment.provider_id, deployment.id, deployment.model, sorted(kwargs.keys()))
            print(f"[provider.start] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete options={sorted(kwargs.keys())}", flush=True)
            resp = self.client.messages.create(**kwargs)
            text = self._extract_text(resp)
            log_info('Provider response done provider=%s deployment=%s model=%s mode=complete chars=%s', deployment.provider_id, deployment.id, deployment.model, len(text or ''))
            print(f"[provider.done] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete chars={len(text or '')}", flush=True)
            return ChatResult(
                text=text,
                provider_id=deployment.provider_id,
                deployment_id=deployment.id,
                model=deployment.model,
                raw=resp,
            )
        except APIStatusError as e:
            payload = anthropic_error_payload(e)
            log_warn('Provider request failed provider=%s deployment=%s model=%s mode=complete status=%s message=%s', deployment.provider_id, deployment.id, deployment.model, payload.get('status_code'), extract_error_message(payload))
            print(f"[provider.error] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete status={payload.get('status_code')} message={extract_error_message(payload)}", flush=True)
            raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e
        except Exception as e:
            payload = anthropic_generic_error_payload(e)
            log_warn('Provider request failed provider=%s deployment=%s model=%s mode=complete status=%s message=%s', deployment.provider_id, deployment.id, deployment.model, payload.get('status_code'), extract_error_message(payload))
            print(f"[provider.error] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete status={payload.get('status_code')} message={extract_error_message(payload)}", flush=True)
            raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e

    def stream_text(self, deployment: ResolvedDeployment, model_input: ModelInput, request_options: dict[str, Any] | None = None) -> Iterator[Any]:
        try:
            kwargs = self._request_kwargs(deployment, model_input, request_options)
            log_info('Provider request start provider=%s deployment=%s model=%s mode=stream options=%s', deployment.provider_id, deployment.id, deployment.model, sorted(kwargs.keys()))
            print(f"[provider.start] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream options={sorted(kwargs.keys())}", flush=True)
            text_chunks = 0
            reasoning_events = 0
            saw_reasoning = False
            thinking_buffers: dict[int, str] = {}
            thinking_done: set[int] = set()
            with self.client.messages.stream(**kwargs) as stream:
                for event in stream:
                    event_type = str(_event_get(event, 'type') or '')
                    if event_type == 'content_block_delta':
                        delta_type = str(_event_get(event, 'delta', 'type') or '')
                        if delta_type == 'text_delta':
                            text = str(_event_get(event, 'delta', 'text') or '')
                            if text:
                                text_chunks += 1
                                yield text
                        elif delta_type == 'thinking_delta':
                            text = str(_event_get(event, 'delta', 'thinking') or '')
                            block_index = int(_event_get(event, 'index') or 0)
                            if text:
                                reasoning_events += 1
                                thinking_buffers[block_index] = f"{thinking_buffers.get(block_index, '')}{text}"
                                if not saw_reasoning:
                                    saw_reasoning = True
                                    log_info('Provider reasoning stream detected provider=%s deployment=%s model=%s event=%s', deployment.provider_id, deployment.id, deployment.model, 'content_block_delta.thinking_delta')
                                    print(f"[provider.reasoning] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} event=content_block_delta.thinking_delta", flush=True)
                                yield {
                                    'type': 'reasoning_delta',
                                    'delta': text,
                                    'text': '',
                                    'part_text': '',
                                    'part_type': 'thinking',
                                    'summary_index': block_index,
                                    'item_id': f'anthropic-thinking-{block_index}',
                                    'event_type': 'content_block_delta.thinking_delta',
                                }
                        elif delta_type == 'signature_delta':
                            continue
                    elif event_type == 'content_block_start':
                        block_type = str(_event_get(event, 'content_block', 'type') or '')
                        if block_type == 'thinking':
                            block_index = int(_event_get(event, 'index') or 0)
                            text = str(_event_get(event, 'content_block', 'thinking') or '')
                            if text:
                                reasoning_events += 1
                                thinking_buffers[block_index] = text
                                if not saw_reasoning:
                                    saw_reasoning = True
                                    log_info('Provider reasoning stream detected provider=%s deployment=%s model=%s event=%s', deployment.provider_id, deployment.id, deployment.model, 'content_block_start.thinking')
                                    print(f"[provider.reasoning] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} event=content_block_start.thinking", flush=True)
                                yield {
                                    'type': 'reasoning_delta',
                                    'delta': text,
                                    'text': '',
                                    'part_text': '',
                                    'part_type': 'thinking',
                                    'summary_index': block_index,
                                    'item_id': f'anthropic-thinking-{block_index}',
                                    'event_type': 'content_block_start.thinking',
                                }
                    elif event_type == 'content_block_stop':
                        block_index = int(_event_get(event, 'index') or 0)
                        text = str(thinking_buffers.get(block_index) or '').strip()
                        if text and block_index not in thinking_done:
                            thinking_done.add(block_index)
                            yield {
                                'type': 'reasoning_done',
                                'delta': '',
                                'text': text,
                                'part_text': '',
                                'part_type': 'thinking',
                                'summary_index': block_index,
                                'item_id': f'anthropic-thinking-{block_index}',
                                'event_type': 'content_block_stop.thinking',
                            }
            log_info('Provider response done provider=%s deployment=%s model=%s mode=stream text_chunks=%s reasoning_events=%s', deployment.provider_id, deployment.id, deployment.model, text_chunks, reasoning_events)
            print(f"[provider.done] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream text_chunks={text_chunks} reasoning_events={reasoning_events}", flush=True)
        except APIStatusError as e:
            payload = anthropic_error_payload(e)
            log_warn('Provider request failed provider=%s deployment=%s model=%s mode=stream status=%s message=%s', deployment.provider_id, deployment.id, deployment.model, payload.get('status_code'), extract_error_message(payload))
            print(f"[provider.error] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream status={payload.get('status_code')} message={extract_error_message(payload)}", flush=True)
            raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e
        except Exception as e:
            payload = anthropic_generic_error_payload(e)
            log_warn('Provider request failed provider=%s deployment=%s model=%s mode=stream status=%s message=%s', deployment.provider_id, deployment.id, deployment.model, payload.get('status_code'), extract_error_message(payload))
            print(f"[provider.error] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream status={payload.get('status_code')} message={extract_error_message(payload)}", flush=True)
            raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e

    def list_models(self, provider: ProviderDef) -> list[ModelInfo]:
        out: list[ModelInfo] = []
        for mid, meta in sorted(self.model_catalog.items()):
            if not isinstance(meta, dict):
                continue
            vendor = str(meta.get('vendor', '') or '').strip().lower()
            tags = tuple(meta.get('tags', []) or [])
            if vendor != 'anthropic' and 'provider:anthropic' not in tags:
                continue
            out.append(
                ModelInfo(
                    id=mid,
                    provider_id=provider.id,
                    provider_type=provider.type,
                    vendor=meta.get('vendor', 'Anthropic'),
                    display_name=meta.get('display_name', mid),
                    description=meta.get('description', ''),
                    created=None,
                    owned_by='anthropic',
                    input_cost_per_million=meta.get('input_cost_per_million'),
                    output_cost_per_million=meta.get('output_cost_per_million'),
                    context_window=meta.get('context_window'),
                    tags=tags,
                )
            )
        return out

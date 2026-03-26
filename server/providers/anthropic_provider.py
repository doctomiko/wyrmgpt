from __future__ import annotations

from typing import Any, Iterator

from anthropic import APIStatusError, Anthropic

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
        for key in ('temperature', 'top_p', 'top_k', 'stop_sequences', 'metadata'):
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
            resp = self.client.messages.create(
                **self._request_kwargs(deployment, model_input, request_options)
            )
            return ChatResult(
                text=self._extract_text(resp),
                provider_id=deployment.provider_id,
                deployment_id=deployment.id,
                model=deployment.model,
                raw=resp,
            )
        except APIStatusError as e:
            payload = anthropic_error_payload(e)
            raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e
        except Exception as e:
            payload = anthropic_generic_error_payload(e)
            raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e

    def stream_text(self, deployment: ResolvedDeployment, model_input: ModelInput, request_options: dict[str, Any] | None = None) -> Iterator[str]:
        try:
            with self.client.messages.stream(
                **self._request_kwargs(deployment, model_input, request_options)
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        yield text
        except APIStatusError as e:
            payload = anthropic_error_payload(e)
            raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e
        except Exception as e:
            payload = anthropic_generic_error_payload(e)
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

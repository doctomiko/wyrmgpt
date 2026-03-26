from __future__ import annotations

from typing import Any, Iterator

from openai import APIStatusError, OpenAI

from .message_transforms import to_openai_chat_messages
from .openai_provider import (
    ProviderExecutionError,
    _default_vendor,
    extract_error_message,
    openai_error_payload,
)
from .types import ChatResult, ModelCatalog, ModelInfo, ModelInput, ProviderDef, ResolvedDeployment


class GoogleProvider:
    def __init__(self, provider_def: ProviderDef, model_catalog: ModelCatalog | None = None):
        kwargs: dict[str, Any] = {}
        api_key = (provider_def.api_key or '').strip()
        if api_key:
            kwargs['api_key'] = api_key
        if provider_def.base_url:
            kwargs['base_url'] = provider_def.base_url
        self.client = OpenAI(**kwargs)
        self.provider_def = provider_def
        self.model_catalog = model_catalog or {}

    def _translate_request_options(self, request_options: dict[str, Any] | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in dict(request_options or {}).items():
            if value is None:
                continue
            if key == 'max_output_tokens':
                out['max_tokens'] = value
            else:
                out[key] = value
        return out

    def _extract_text(self, resp: Any) -> str:
        choices = getattr(resp, 'choices', None) or []
        chunks: list[str] = []
        for choice in choices:
            message = getattr(choice, 'message', None)
            if message is None:
                continue
            content = getattr(message, 'content', None)
            if isinstance(content, str):
                if content:
                    chunks.append(content)
                continue
            if isinstance(content, list):
                for part in content:
                    text = None
                    if isinstance(part, dict):
                        text = part.get('text')
                    else:
                        text = getattr(part, 'text', None)
                    if isinstance(text, str) and text:
                        chunks.append(text)
        return ''.join(chunks).strip()

    def complete(
        self,
        deployment: ResolvedDeployment,
        model_input: ModelInput,
        request_options: dict[str, Any] | None = None,
    ) -> ChatResult:
        try:
            resp = self.client.chat.completions.create(
                model=deployment.model,
                messages=to_openai_chat_messages(model_input),
                **self._translate_request_options(request_options),
            )
            return ChatResult(
                text=self._extract_text(resp),
                provider_id=deployment.provider_id,
                deployment_id=deployment.id,
                model=deployment.model,
                raw=resp,
            )
        except APIStatusError as e:
            payload = openai_error_payload(e)
            raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e

    def stream_text(self, deployment: ResolvedDeployment, model_input: ModelInput) -> Iterator[str]:
        try:
            stream = self.client.chat.completions.create(
                model=deployment.model,
                messages=to_openai_chat_messages(model_input),
                stream=True,
            )
            for chunk in stream:
                choices = getattr(chunk, 'choices', None) or []
                for choice in choices:
                    delta = getattr(choice, 'delta', None)
                    if delta is None:
                        continue
                    content = getattr(delta, 'content', None)
                    if isinstance(content, str):
                        if content:
                            yield content
                        continue
                    if isinstance(content, list):
                        for part in content:
                            text = None
                            if isinstance(part, dict):
                                text = part.get('text')
                            else:
                                text = getattr(part, 'text', None)
                            if isinstance(text, str) and text:
                                yield text
        except APIStatusError as e:
            payload = openai_error_payload(e)
            raise ProviderExecutionError(extract_error_message(payload), payload=payload) from e

    def list_models(self, provider: ProviderDef) -> list[ModelInfo]:
        out: list[ModelInfo] = []
        model_objs = self.client.models.list()
        for m in model_objs:
            mid = getattr(m, 'id', None)
            if not mid:
                continue
            meta = self.model_catalog.get(mid, {})
            out.append(
                ModelInfo(
                    id=mid,
                    provider_id=provider.id,
                    provider_type=provider.type,
                    vendor=meta.get('vendor', _default_vendor(provider)),
                    display_name=meta.get('display_name', mid),
                    description=meta.get('description', ''),
                    created=getattr(m, 'created', None),
                    owned_by=getattr(m, 'owned_by', None),
                    input_cost_per_million=meta.get('input_cost_per_million'),
                    output_cost_per_million=meta.get('output_cost_per_million'),
                    context_window=meta.get('context_window'),
                    tags=tuple(meta.get('tags', [])),
                )
            )
        return out

from __future__ import annotations

from typing import Any, Iterator
import json

from openai import APIStatusError, OpenAI

from server.logging_helper import log_debug, log_info, log_warn
from .message_transforms import to_openai_chat_messages
from .openai_provider import (
    ProviderExecutionError,
    _default_vendor,
    extract_error_message,
    format_error_diagnostics,
    openai_error_payload,
)
from .types import ChatResult, ModelCatalog, ModelInfo, ModelInput, ProviderDef, ResolvedDeployment


def _maybe_model_dump(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    dump = getattr(value, 'model_dump', None)
    if callable(dump):
        try:
            return dump(exclude_none=True)
        except Exception:
            pass
    return value


def _strip_google_thought_prefix(text: Any) -> str:
    raw = str(text or '')
    if not raw:
        return ''
    if raw.startswith('<thought>'):
        raw = raw[len('<thought>'): ]
    return raw


def _google_extra_google(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    extra_content = raw.get('extra_content')
    if not isinstance(extra_content, dict):
        return {}
    google = extra_content.get('google')
    if not isinstance(google, dict):
        return {}
    return google


def _google_content_thought_state(raw: Any) -> tuple[bool, str | None]:
    google = _google_extra_google(raw)
    is_thought = bool(google.get('thought') or google.get('is_thought'))
    thought_signature = google.get('thought_signature')
    if thought_signature is not None:
        thought_signature = str(thought_signature or '').strip() or None
    return is_thought, thought_signature

def _google_signature_only_placeholder() -> str:
    return "**Signature-only thinking**\n\nGemini emitted a thought signature for this turn, but no visible thought summary text was exposed through the OpenAI-compatible stream."


def _google_thinking_candidate_from_part(part: Any) -> tuple[str, bool]:
    raw = _maybe_model_dump(part)
    if not isinstance(raw, dict):
        return '', False
    text = _strip_google_thought_prefix(raw.get('text'))
    if not text:
        return '', False
    is_thought = bool(raw.get('thought') or raw.get('is_thought'))
    part_type = str(raw.get('type') or '').strip().lower()
    if part_type in {'thought', 'reasoning', 'thinking'}:
        is_thought = True
    return text, is_thought


def _iter_google_reasoning_candidates_from_value(value: Any) -> Iterator[str]:
    raw = _maybe_model_dump(value)
    if isinstance(raw, list):
        for item in raw:
            yield from _iter_google_reasoning_candidates_from_value(item)
        return
    if not isinstance(raw, dict):
        return

    text = _strip_google_thought_prefix(raw.get('text')).strip()
    is_thought = bool(raw.get('thought') or raw.get('is_thought'))
    kind = str(raw.get('type') or '').strip().lower()
    extra_thought, _sig = _google_content_thought_state(raw)
    if text and (is_thought or extra_thought or kind in {'thought', 'thinking', 'reasoning', 'reasoning_text', 'reasoning_summary'}):
        yield text

    content_text = _strip_google_thought_prefix(raw.get('content')).strip()
    if content_text and extra_thought:
        yield content_text

    for key in ('content', 'parts', 'reasoning', 'thinking', 'thought', 'thoughts', 'summary', 'summaries', 'reasoning_content', 'reasoning_parts'):
        if key in raw:
            yield from _iter_google_reasoning_candidates_from_value(raw.get(key))

    extra_content = raw.get('extra_content')
    if isinstance(extra_content, dict):
        google = extra_content.get('google')
        if google is not None:
            yield from _iter_google_reasoning_candidates_from_value(google)


def _compact_json(value: Any, limit: int = 1200) -> str:
    try:
        raw = _maybe_model_dump(value)
        dumped = json.dumps(raw, ensure_ascii=False, default=str)
    except Exception:
        dumped = repr(value)
    dumped = dumped.strip()
    if len(dumped) > limit:
        return dumped[:limit] + '…'
    return dumped


def _choice_message_content(choice: Any) -> Any:
    message = getattr(choice, 'message', None)
    if message is None and isinstance(choice, dict):
        message = choice.get('message')
    if message is None:
        return None
    if isinstance(message, dict):
        return message.get('content')
    return getattr(message, 'content', None)


def _extract_text(resp: Any) -> str:
    choices = getattr(resp, 'choices', None) or []
    chunks: list[str] = []
    for choice in choices:
        content = _choice_message_content(choice)
        if isinstance(content, str):
            if content:
                chunks.append(content)
            continue
        if isinstance(content, list):
            for part in content:
                text, is_thought = _google_thinking_candidate_from_part(part)
                if text and not is_thought:
                    chunks.append(text)
    return ''.join(chunks).strip()


def _iter_google_reasoning_fallbacks(resp: Any) -> Iterator[str]:
    choices = getattr(resp, 'choices', None) or []
    seen: set[str] = set()
    for choice in choices:
        content = _choice_message_content(choice)
        if not isinstance(content, list):
            continue
        for part in content:
            text, is_thought = _google_thinking_candidate_from_part(part)
            cleaned = str(text or '').strip()
            if cleaned and is_thought and cleaned not in seen:
                seen.add(cleaned)
                yield cleaned


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

    def _normalize_extra_body_for_python_sdk(self, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if 'extra_body' in value:
            return value
        if 'google' in value:
            # Google's Python OpenAI-compat examples use an extra nested
            # `extra_body` wrapper, while the REST/JS examples do not.
            wrapped = {'extra_body': value}
            log_debug('Google provider wrapped extra_body for Python SDK: %s', sorted(value.keys()))
            return wrapped
        return value

    def _translate_request_options(self, request_options: dict[str, Any] | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in dict(request_options or {}).items():
            if value is None:
                continue
            if key == 'max_output_tokens':
                out['max_tokens'] = value
            elif key == 'extra_body':
                out['extra_body'] = self._normalize_extra_body_for_python_sdk(value)
            else:
                out[key] = value
        return out

    def complete(
        self,
        deployment: ResolvedDeployment,
        model_input: ModelInput,
        request_options: dict[str, Any] | None = None,
    ) -> ChatResult:
        try:
            kwargs = self._translate_request_options(request_options)
            log_info('Provider request start provider=%s deployment=%s model=%s mode=complete options=%s', deployment.provider_id, deployment.id, deployment.model, sorted(kwargs.keys()))
            print(f"[provider.start] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete options={sorted(kwargs.keys())}", flush=True)
            resp = self.client.chat.completions.create(
                model=deployment.model,
                messages=to_openai_chat_messages(model_input),
                **kwargs,
            )
            text = _extract_text(resp)
            reasoning_count = sum(1 for _ in _iter_google_reasoning_fallbacks(resp))
            log_info('Provider response done provider=%s deployment=%s model=%s mode=complete chars=%s reasoning_events=%s', deployment.provider_id, deployment.id, deployment.model, len(text or ''), reasoning_count)
            print(f"[provider.done] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete chars={len(text or '')} reasoning_events={reasoning_count}", flush=True)
            return ChatResult(
                text=text,
                provider_id=deployment.provider_id,
                deployment_id=deployment.id,
                model=deployment.model,
                raw=resp,
            )
        except APIStatusError as e:
            payload = openai_error_payload(e)
            details = format_error_diagnostics(payload)
            if (
                'Unknown name "google"' in str(details or '')
                and isinstance(kwargs.get('extra_body'), dict)
                and 'google' in kwargs.get('extra_body', {})
                and 'extra_body' not in kwargs.get('extra_body', {})
            ):
                wrapped_kwargs = dict(kwargs)
                wrapped_kwargs['extra_body'] = {'extra_body': kwargs['extra_body']}
                log_warn('Google provider retrying complete request with nested extra_body wrapper for deployment=%s model=%s', deployment.id, deployment.model)
                print(f"[provider.retry] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete wrapped=extra_body", flush=True)
                resp = self.client.chat.completions.create(
                    model=deployment.model,
                    messages=to_openai_chat_messages(model_input),
                    **wrapped_kwargs,
                )
                text = _extract_text(resp)
                reasoning_count = sum(1 for _ in _iter_google_reasoning_fallbacks(resp))
                log_info('Provider response done provider=%s deployment=%s model=%s mode=complete chars=%s reasoning_events=%s', deployment.provider_id, deployment.id, deployment.model, len(text or ''), reasoning_count)
                print(f"[provider.done] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete chars={len(text or '')} reasoning_events={reasoning_count}", flush=True)
                return ChatResult(
                    text=text,
                    provider_id=deployment.provider_id,
                    deployment_id=deployment.id,
                    model=deployment.model,
                    raw=resp,
                )
            log_warn('Provider request failed provider=%s deployment=%s model=%s mode=complete status=%s details=%s', deployment.provider_id, deployment.id, deployment.model, payload.get('status_code'), details)
            print(f"[provider.error] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete status={payload.get('status_code')} details={details}", flush=True)
            raise ProviderExecutionError(details, payload=payload) from e
        except Exception as e:
            payload = {
                'status_code': None,
                'request_id': None,
                'body': {'message': str(e) or repr(e)},
                'provider_error_type': type(e).__name__,
            }
            details = format_error_diagnostics(payload)
            log_warn('Provider request failed provider=%s deployment=%s model=%s mode=complete status=%s details=%s', deployment.provider_id, deployment.id, deployment.model, payload.get('status_code'), details)
            print(f"[provider.error] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=complete status={payload.get('status_code')} details={details}", flush=True)
            raise ProviderExecutionError(details, payload=payload) from e

    def stream_text(self, deployment: ResolvedDeployment, model_input: ModelInput, request_options: dict[str, Any] | None = None) -> Iterator[Any]:
        try:
            kwargs = self._translate_request_options(request_options)
            log_info('Provider request start provider=%s deployment=%s model=%s mode=stream options=%s', deployment.provider_id, deployment.id, deployment.model, sorted(kwargs.keys()))
            print(f"[provider.start] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream options={sorted(kwargs.keys())}", flush=True)
            text_chunks = 0
            reasoning_events = 0
            saw_reasoning = False
            delta_samples: list[str] = []
            signature_only_marker: str | None = None
            stream = self.client.chat.completions.create(
                model=deployment.model,
                messages=to_openai_chat_messages(model_input),
                stream=True,
                **kwargs,
            )
            for chunk in stream:
                choices = getattr(chunk, 'choices', None) or []
                for choice in choices:
                    delta = getattr(choice, 'delta', None)
                    if delta is None and isinstance(choice, dict):
                        delta = choice.get('delta')
                    if delta is None:
                        continue
                    delta_raw = _maybe_model_dump(delta)
                    if len(delta_samples) < 3:
                        delta_samples.append(_compact_json(delta_raw))
                    if isinstance(delta_raw, dict):
                        content_marked_thought, thought_signature = _google_content_thought_state(delta_raw)
                    else:
                        content_marked_thought, thought_signature = False, None
                    if thought_signature and not signature_only_marker:
                        signature_only_marker = str(thought_signature)

                    emitted_reasoning = False
                    for candidate_text in _iter_google_reasoning_candidates_from_value(delta_raw):
                        cleaned_candidate = str(candidate_text or '').strip()
                        if not cleaned_candidate:
                            continue
                        reasoning_events += 1
                        emitted_reasoning = True
                        if not saw_reasoning:
                            saw_reasoning = True
                            log_info('Provider reasoning stream detected provider=%s deployment=%s model=%s event=%s', deployment.provider_id, deployment.id, deployment.model, 'google.delta_probe')
                            print(f"[provider.reasoning] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} event=google.delta_probe", flush=True)
                        yield {
                            'type': 'reasoning_delta',
                            'delta': cleaned_candidate,
                            'text': '',
                            'part_text': '',
                            'part_type': 'thought',
                            'summary_index': None,
                            'item_id': thought_signature,
                            'event_type': 'google.delta_probe',
                        }

                    content = getattr(delta, 'content', None)
                    if content is None and isinstance(delta_raw, dict):
                        content = delta_raw.get('content')
                    if isinstance(content, str):
                        raw_text = _strip_google_thought_prefix(content)
                        if raw_text and (content_marked_thought or thought_signature) and not emitted_reasoning:
                            reasoning_events += 1
                            emitted_reasoning = True
                            if not saw_reasoning:
                                saw_reasoning = True
                                detected_event = 'google.extra_content_thought' if content_marked_thought else 'google.thought_signature'
                                log_info('Provider reasoning stream detected provider=%s deployment=%s model=%s event=%s', deployment.provider_id, deployment.id, deployment.model, detected_event)
                                print(f"[provider.reasoning] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} event={detected_event}", flush=True)
                            yield {
                                'type': 'reasoning_delta',
                                'delta': raw_text,
                                'text': '',
                                'part_text': '',
                                'part_type': 'thought',
                                'summary_index': None,
                                'item_id': thought_signature,
                                'event_type': 'google.extra_content_thought' if content_marked_thought else 'google.thought_signature',
                            }
                        elif raw_text:
                            text_chunks += 1
                            yield raw_text
                        continue
                    if isinstance(content, list):
                        for part in content:
                            text, is_thought = _google_thinking_candidate_from_part(part)
                            if not text:
                                continue
                            if is_thought:
                                reasoning_events += 1
                                if not saw_reasoning:
                                    saw_reasoning = True
                                    log_info('Provider reasoning stream detected provider=%s deployment=%s model=%s event=%s', deployment.provider_id, deployment.id, deployment.model, 'google.content_part')
                                    print(f"[provider.reasoning] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} event=google.content_part", flush=True)
                                yield {
                                    'type': 'reasoning_delta',
                                    'delta': text,
                                    'text': '',
                                    'part_text': '',
                                    'part_type': 'thought',
                                    'summary_index': None,
                                    'item_id': None,
                                    'event_type': 'google.content_part',
                                }
                            else:
                                text_chunks += 1
                                yield text
            if reasoning_events == 0 and signature_only_marker:
                reasoning_events += 1
                log_info('Provider reasoning stream detected provider=%s deployment=%s model=%s event=%s', deployment.provider_id, deployment.id, deployment.model, 'google.signature_only')
                print(f"[provider.reasoning] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} event=google.signature_only", flush=True)
                yield {
                    'type': 'reasoning_done',
                    'delta': '',
                    'text': _google_signature_only_placeholder(),
                    'part_text': '',
                    'part_type': 'signature_only',
                    'summary_index': None,
                    'item_id': signature_only_marker,
                    'event_type': 'google.signature_only',
                    'done': True,
                }
            if reasoning_events == 0:
                log_warn('Google stream produced no reasoning events provider=%s deployment=%s model=%s request_extra_body=%s delta_samples=%s', deployment.provider_id, deployment.id, deployment.model, _compact_json(kwargs.get('extra_body')), delta_samples)
                print(f"[provider.reasoning.none] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} extra_body={_compact_json(kwargs.get('extra_body'), 400)} delta_samples={_compact_json(delta_samples, 900)}", flush=True)
            log_info('Provider response done provider=%s deployment=%s model=%s mode=stream text_chunks=%s reasoning_events=%s', deployment.provider_id, deployment.id, deployment.model, text_chunks, reasoning_events)
            print(f"[provider.done] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream text_chunks={text_chunks} reasoning_events={reasoning_events}", flush=True)
        except APIStatusError as e:
            payload = openai_error_payload(e)
            details = format_error_diagnostics(payload)
            if (
                'Unknown name "google"' in str(details or '')
                and isinstance(kwargs.get('extra_body'), dict)
                and 'google' in kwargs.get('extra_body', {})
                and 'extra_body' not in kwargs.get('extra_body', {})
            ):
                wrapped_kwargs = dict(kwargs)
                wrapped_kwargs['extra_body'] = {'extra_body': kwargs['extra_body']}
                log_warn('Google provider retrying stream request with nested extra_body wrapper for deployment=%s model=%s', deployment.id, deployment.model)
                print(f"[provider.retry] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream wrapped=extra_body", flush=True)
                stream = self.client.chat.completions.create(
                    model=deployment.model,
                    messages=to_openai_chat_messages(model_input),
                    stream=True,
                    **wrapped_kwargs,
                )
                text_chunks = 0
                reasoning_events = 0
                saw_reasoning = False
                for chunk in stream:
                    choices = getattr(chunk, 'choices', None) or []
                    for choice in choices:
                        delta = getattr(choice, 'delta', None)
                        if delta is None and isinstance(choice, dict):
                            delta = choice.get('delta')
                        if delta is None:
                            continue
                        delta_raw = _maybe_model_dump(delta)
                        if isinstance(delta_raw, dict):
                            content_marked_thought, thought_signature = _google_content_thought_state(delta_raw)
                        else:
                            content_marked_thought, thought_signature = False, None
                        content = getattr(delta, 'content', None)
                        if content is None and isinstance(delta_raw, dict):
                            content = delta_raw.get('content')
                        if isinstance(content, str):
                            raw_text = _strip_google_thought_prefix(content)
                            if raw_text and (content_marked_thought or thought_signature):
                                reasoning_events += 1
                                if not saw_reasoning:
                                    saw_reasoning = True
                                    detected_event = 'google.extra_content_thought' if content_marked_thought else 'google.thought_signature'
                                    log_info('Provider reasoning stream detected provider=%s deployment=%s model=%s event=%s', deployment.provider_id, deployment.id, deployment.model, detected_event)
                                    print(f"[provider.reasoning] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} event={detected_event}", flush=True)
                                yield {
                                    'type': 'reasoning_delta',
                                    'delta': raw_text,
                                    'text': '',
                                    'part_text': '',
                                    'part_type': 'thought',
                                    'summary_index': None,
                                    'item_id': thought_signature,
                                    'event_type': 'google.extra_content_thought' if content_marked_thought else 'google.thought_signature',
                                }
                            elif raw_text:
                                text_chunks += 1
                                yield raw_text
                            continue
                        if isinstance(content, list):
                            for part in content:
                                part_text, is_thought = _google_thinking_candidate_from_part(part)
                                if not part_text:
                                    continue
                                if is_thought:
                                    reasoning_events += 1
                                    if not saw_reasoning:
                                        saw_reasoning = True
                                        log_info('Provider reasoning stream detected provider=%s deployment=%s model=%s event=%s', deployment.provider_id, deployment.id, deployment.model, 'google.content_part')
                                        print(f"[provider.reasoning] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} event=google.content_part", flush=True)
                                    yield {
                                        'type': 'reasoning_delta',
                                        'delta': part_text,
                                        'text': '',
                                        'part_text': '',
                                        'part_type': 'thought',
                                        'summary_index': None,
                                        'item_id': None,
                                        'event_type': 'google.content_part',
                                    }
                                else:
                                    text_chunks += 1
                                    yield part_text
                if reasoning_events == 0:
                    log_warn('Google stream produced no reasoning events provider=%s deployment=%s model=%s request_extra_body=%s', deployment.provider_id, deployment.id, deployment.model, _compact_json(wrapped_kwargs.get('extra_body')))
                    print(f"[provider.reasoning.none] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} extra_body={_compact_json(wrapped_kwargs.get('extra_body'), 400)}", flush=True)
                log_info('Provider response done provider=%s deployment=%s model=%s mode=stream text_chunks=%s reasoning_events=%s', deployment.provider_id, deployment.id, deployment.model, text_chunks, reasoning_events)
                print(f"[provider.done] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream text_chunks={text_chunks} reasoning_events={reasoning_events}", flush=True)
                return
            log_warn('Provider request failed provider=%s deployment=%s model=%s mode=stream status=%s details=%s', deployment.provider_id, deployment.id, deployment.model, payload.get('status_code'), details)
            print(f"[provider.error] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream status={payload.get('status_code')} details={details}", flush=True)
            raise ProviderExecutionError(details, payload=payload) from e
        except Exception as e:
            payload = {
                'status_code': None,
                'request_id': None,
                'body': {'message': str(e) or repr(e)},
                'provider_error_type': type(e).__name__,
            }
            details = format_error_diagnostics(payload)
            log_warn('Provider request failed provider=%s deployment=%s model=%s mode=stream status=%s details=%s', deployment.provider_id, deployment.id, deployment.model, payload.get('status_code'), details)
            print(f"[provider.error] provider={deployment.provider_id} deployment={deployment.id} model={deployment.model} mode=stream status={payload.get('status_code')} details={details}", flush=True)
            raise ProviderExecutionError(details, payload=payload) from e

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

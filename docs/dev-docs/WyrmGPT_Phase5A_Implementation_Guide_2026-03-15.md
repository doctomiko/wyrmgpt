# WyrmGPT Phase 5A Implementation Guide

Checked against `WyrmGPT.20260315.a.zip` on March 15, 2026.

This is the **literal implementation guide** for Phase 5A.
It is written to maximize velocity, keep frontend breakage at zero, and avoid turning the provider refactor into a total-body transplant.

## First: what the `...` meant

In Python, `...` inside a protocol or stub method is not a magic omission from me. It is the built-in `Ellipsis` object and is commonly used as a placeholder body for interfaces, type stubs, or methods that have no implementation in that file.

Example:

```python
class Thing(Protocol):
    def run(self) -> str: ...
```

That means “this method must exist with this signature,” not “details omitted.”

That said, for this phase the user wants the **full sequence**, so this guide spells out the real steps and concrete code shapes.

## What Phase 5A is actually trying to do

Phase 5A is **not** “support Ollama today.”

Phase 5A is this:

1. remove direct OpenAI chat/model-list execution from `server/main.py`
2. add provider interfaces for chat and model catalog
3. add a provider/deployment registry
4. keep the current UI working without any frontend changes
5. keep summary code alone for now
6. keep embeddings alone for now

The app should still behave the same from the browser’s point of view.
The change is internal: `main.py` stops being the OpenAI client’s chauffeur.

## What the repo looks like right now

### Current OpenAI weld points

In `server/main.py` right now:

- `client = OpenAI(api_key=oai_cfg.open_ai_apikey)`
- `/api/chat` directly does `client.responses.stream(...)`
- `_call_model()` directly does `client.responses.create(...)`
- `/api/models` directly does `client.models.list()`
- `call_model_with_recovery()` catches `APIStatusError`
- `chat_ab()` depends on `_call_model()` and OpenAI-style errors

### Current provider groundwork

You already have:

- `server/providers/base.py` with `EmbeddingProvider`
- `server/providers/openai_embeddings.py`
- TOML provider config under `[providers.openai]`

That is enough to start the grown-up provider layer.

## The rule that keeps 5A sane

For 5A, **do not redesign the request payload yet**.

Keep using the existing `build_model_input(...)` output, which is currently OpenAI-shaped enough to work.

The provider layer in 5A is only responsible for:

- executing a chat request
- streaming a chat request
- listing models
- normalizing provider errors

The deeper “Wyrm-native request object” refactor belongs later, after the spine exists.

---

# Step 1: add `server/providers/types.py`

Create a brand new file at `server/providers/types.py`.

Paste this in as the starting point:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderDef:
    id: str
    type: str
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class DeploymentDef:
    id: str
    provider: str
    model: str
    display_name: str = ""
    capabilities: tuple[str, ...] = ()
    enabled: bool = True
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedDeployment:
    id: str
    provider_id: str
    provider_type: str
    model: str
    display_name: str
    capabilities: tuple[str, ...]
    base_url: str = ""
    tags: tuple[str, ...] = ()
    is_ephemeral: bool = False


@dataclass
class ProviderErrorInfo:
    provider_id: str
    deployment_id: str | None
    model: str | None
    message: str
    status_code: int | None = None
    request_id: str | None = None
    provider_error_type: str | None = None
    raw: Any = None
    recovery_step: str | None = None


class ProviderExecutionError(RuntimeError):
    def __init__(self, info: ProviderErrorInfo):
        super().__init__(info.message)
        self.info = info


@dataclass
class ChatResult:
    text: str
    provider_id: str
    deployment_id: str | None
    model: str
    raw: Any = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider_id: str
    provider_type: str
    vendor: str
    display_name: str
    description: str = ""
    created: int | None = None
    owned_by: str | None = None
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    context_window: int | None = None
    tags: tuple[str, ...] = ()
```

Why this file exists:

- `config.py` can use these dataclasses
- the registry can use them
- provider implementations can use them
- `main.py` can catch `ProviderExecutionError`

This becomes the shared vocabulary for Phase 5.

---

# Step 2: replace `server/providers/base.py`

Your current `server/providers/base.py` only has `EmbeddingProvider`.
Replace the file with this:

```python
from __future__ import annotations

from typing import Any, Iterator, Protocol

from .types import (
    ChatResult,
    ModelInfo,
    ProviderDef,
    ResolvedDeployment,
)


class ChatProvider(Protocol):
    def complete(self, deployment: ResolvedDeployment, model_input: list[dict[str, Any]]) -> ChatResult:
        ...

    def stream_text(self, deployment: ResolvedDeployment, model_input: list[dict[str, Any]]) -> Iterator[str]:
        ...


class ModelCatalogProvider(Protocol):
    def list_models(self, provider: ProviderDef) -> list[ModelInfo]:
        ...


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...
```

This is an interface file, so the `...` bodies are correct here.

---

# Step 3: teach `config.py` how to load providers and deployments

You already have TOML loading infrastructure in `server/config.py`.
Use it.
Do **not** build a second config parser.

## 3.1 Add imports near the top

In `server/config.py`, add this import near the other imports:

```python
from .providers.types import ProviderDef, DeploymentDef
```

That import is safe because `providers/types.py` does not import `config.py`.

## 3.2 Add provider/deployment loaders

Add these functions in `server/config.py` after `load_openai_config()` or near the other loaders:

```python
def load_provider_defs() -> dict[str, ProviderDef]:
    raw = _toml_get(("providers",), default={})
    out: dict[str, ProviderDef] = {}

    if isinstance(raw, dict):
        for provider_id, spec in raw.items():
            if not isinstance(spec, dict):
                continue

            provider_type = str(spec.get("type") or provider_id).strip()
            api_key = str(spec.get("api_key") or "").strip()
            base_url = str(spec.get("base_url") or "").strip()
            enabled = _coerce_bool(spec.get("enabled", True), True)

            out[provider_id] = ProviderDef(
                id=provider_id,
                type=provider_type,
                api_key=api_key,
                base_url=base_url,
                enabled=enabled,
            )

    # Backward-compatibility: synthesize openai if missing entirely.
    if "openai" not in out:
        oai = load_openai_config()
        out["openai"] = ProviderDef(
            id="openai",
            type="openai",
            api_key=oai.open_ai_apikey,
            base_url="",
            enabled=True,
        )

    return out


def load_deployment_defs() -> dict[str, DeploymentDef]:
    raw = _toml_get(("deployments",), default={})
    out: dict[str, DeploymentDef] = {}

    if isinstance(raw, dict):
        for deployment_id, spec in raw.items():
            if not isinstance(spec, dict):
                continue

            provider = str(spec.get("provider") or "").strip()
            model = str(spec.get("model") or "").strip()
            display_name = str(spec.get("display_name") or deployment_id).strip()
            enabled = _coerce_bool(spec.get("enabled", True), True)

            caps_raw = spec.get("capabilities") or []
            if isinstance(caps_raw, (list, tuple, set)):
                capabilities = tuple(str(x).strip() for x in caps_raw if str(x).strip())
            elif caps_raw:
                capabilities = tuple(x.strip() for x in str(caps_raw).split(",") if x.strip())
            else:
                capabilities = ()

            tags_raw = spec.get("tags") or []
            if isinstance(tags_raw, (list, tuple, set)):
                tags = tuple(str(x).strip() for x in tags_raw if str(x).strip())
            elif tags_raw:
                tags = tuple(x.strip() for x in str(tags_raw).split(",") if x.strip())
            else:
                tags = ()

            if not provider or not model:
                continue

            out[deployment_id] = DeploymentDef(
                id=deployment_id,
                provider=provider,
                model=model,
                display_name=display_name,
                capabilities=capabilities,
                enabled=enabled,
                tags=tags,
            )

    # Backward-compatibility: synthesize deployments if none are declared.
    if not out:
        oai = load_openai_config()
        out["chat_default"] = DeploymentDef(
            id="chat_default",
            provider="openai",
            model=oai.open_ai_model,
            display_name="OpenAI Chat Default",
            capabilities=("chat", "stream", "catalog"),
            enabled=True,
            tags=("default", "chat"),
        )
        out["summary_default"] = DeploymentDef(
            id="summary_default",
            provider="openai",
            model=oai.summary_model,
            display_name="OpenAI Summary Default",
            capabilities=("chat",),
            enabled=True,
            tags=("default", "summary"),
        )

    return out
```

## 3.3 Do not change `load_openai_config()` yet

Leave `load_openai_config()` alone for now.

Reason: summary code and embedding code still use it.
If you change too much at once, you create circular breakage.

---

# Step 4: add `server/providers/registry.py`

Create a new file at `server/providers/registry.py`.

Paste this in as the initial version:

```python
from __future__ import annotations

from typing import Callable

from ..config import load_deployment_defs, load_provider_defs
from .base import ChatProvider, ModelCatalogProvider
from .types import (
    DeploymentDef,
    ProviderDef,
    ResolvedDeployment,
)
from .openai_provider import OpenAIProvider


class ProviderRegistry:
    def __init__(
        self,
        provider_defs: dict[str, ProviderDef],
        deployment_defs: dict[str, DeploymentDef],
        *,
        model_catalog: dict[str, dict] | None = None,
    ) -> None:
        self.provider_defs = provider_defs
        self.deployment_defs = deployment_defs
        self.model_catalog = model_catalog or {}
        self._provider_instances: dict[str, object] = {}

    def _default_chat_deployment(self) -> DeploymentDef:
        if "chat_default" in self.deployment_defs:
            dep = self.deployment_defs["chat_default"]
            if dep.enabled:
                return dep

        for dep in self.deployment_defs.values():
            if dep.enabled and "chat" in dep.capabilities:
                return dep

        raise RuntimeError("No enabled chat deployment configured")

    def _resolve_from_def(self, dep: DeploymentDef) -> ResolvedDeployment:
        provider = self.provider_defs.get(dep.provider)
        if not provider:
            raise RuntimeError(f"Deployment '{dep.id}' refers to unknown provider '{dep.provider}'")
        if not provider.enabled:
            raise RuntimeError(f"Provider '{provider.id}' is disabled")

        return ResolvedDeployment(
            id=dep.id,
            provider_id=provider.id,
            provider_type=provider.type,
            model=dep.model,
            display_name=dep.display_name or dep.id,
            capabilities=dep.capabilities,
            base_url=provider.base_url,
            tags=dep.tags,
            is_ephemeral=False,
        )

    def resolve_chat_target(self, requested: str | None) -> ResolvedDeployment:
        requested = (requested or "").strip()

        # Preferred path: explicit deployment id.
        if requested and requested in self.deployment_defs:
            return self._resolve_from_def(self.deployment_defs[requested])

        # Backward-compatible path: raw model string from existing UI/localStorage.
        if requested:
            default_dep = self._default_chat_deployment()
            provider = self.provider_defs.get(default_dep.provider)
            if not provider:
                raise RuntimeError(f"Default deployment refers to unknown provider '{default_dep.provider}'")

            return ResolvedDeployment(
                id=f"ephemeral::{provider.id}::{requested}",
                provider_id=provider.id,
                provider_type=provider.type,
                model=requested,
                display_name=requested,
                capabilities=default_dep.capabilities,
                base_url=provider.base_url,
                tags=("ephemeral",),
                is_ephemeral=True,
            )

        return self._resolve_from_def(self._default_chat_deployment())

    def _build_provider_instance(self, provider_def: ProviderDef) -> object:
        if provider_def.type == "openai":
            return OpenAIProvider(provider_def=provider_def, model_catalog=self.model_catalog)
        raise RuntimeError(f"Unsupported provider type: {provider_def.type}")

    def _get_provider_instance(self, provider_id: str) -> object:
        if provider_id in self._provider_instances:
            return self._provider_instances[provider_id]

        provider_def = self.provider_defs.get(provider_id)
        if not provider_def:
            raise RuntimeError(f"Unknown provider: {provider_id}")

        inst = self._build_provider_instance(provider_def)
        self._provider_instances[provider_id] = inst
        return inst

    def get_chat_provider(self, deployment: ResolvedDeployment) -> ChatProvider:
        return self._get_provider_instance(deployment.provider_id)  # type: ignore[return-value]

    def get_catalog_provider(self, provider_id: str) -> ModelCatalogProvider:
        return self._get_provider_instance(provider_id)  # type: ignore[return-value]

    def list_models_for_default_provider(self) -> list:
        dep = self._default_chat_deployment()
        provider = self.provider_defs.get(dep.provider)
        if not provider:
            raise RuntimeError(f"Default deployment refers to unknown provider '{dep.provider}'")
        catalog = self.get_catalog_provider(provider.id)
        return catalog.list_models(provider)



def build_provider_registry(*, model_catalog: dict[str, dict] | None = None) -> ProviderRegistry:
    return ProviderRegistry(
        provider_defs=load_provider_defs(),
        deployment_defs=load_deployment_defs(),
        model_catalog=model_catalog or {},
    )
```

Why this file matters:

- `main.py` can ask for a deployment without knowing provider details
- `main.py` can keep accepting raw model strings for now
- future UI migration can switch to deployment IDs without breaking old sessions

That backward-compatibility bridge is essential.

---

# Step 5: add `server/providers/openai_provider.py`

Create a new file at `server/providers/openai_provider.py`.

Use this as your first implementation:

```python
from __future__ import annotations

from typing import Any, Iterator

from openai import OpenAI, APIStatusError

from .types import (
    ChatResult,
    ModelInfo,
    ProviderDef,
    ProviderErrorInfo,
    ProviderExecutionError,
    ResolvedDeployment,
)


_ALLOWED_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4")


class OpenAIProvider:
    def __init__(self, provider_def: ProviderDef, model_catalog: dict[str, dict] | None = None) -> None:
        kwargs: dict[str, str] = {}
        if provider_def.api_key:
            kwargs["api_key"] = provider_def.api_key
        if provider_def.base_url:
            kwargs["base_url"] = provider_def.base_url

        self.client = OpenAI(**kwargs)
        self.provider_def = provider_def
        self.model_catalog = model_catalog or {}

    def _error_info(self, deployment: ResolvedDeployment, e: APIStatusError) -> ProviderErrorInfo:
        status = getattr(e, "status_code", None)
        req_id = None
        err_json: Any = None

        try:
            err_json = e.response.json()
            if isinstance(err_json, dict):
                req_id = (err_json.get("error") or {}).get("request_id") or err_json.get("request_id")
        except Exception:
            try:
                err_json = {"raw": e.response.text}
            except Exception:
                err_json = {"raw": repr(getattr(e, "response", None))}

        message = "OpenAI API error"
        if isinstance(err_json, dict):
            body_error = err_json.get("error") or {}
            message = body_error.get("message") or err_json.get("message") or message

        return ProviderErrorInfo(
            provider_id=self.provider_def.id,
            deployment_id=deployment.id,
            model=deployment.model,
            message=message,
            status_code=status,
            request_id=req_id,
            provider_error_type=type(e).__name__,
            raw=err_json,
        )

    def _extract_output_text(self, resp: Any) -> str:
        try:
            txt = getattr(resp, "output_text", None)
            if txt and str(txt).strip():
                return str(txt).strip()
        except Exception:
            pass

        parts: list[str] = []

        try:
            for item in getattr(resp, "output", []) or []:
                if getattr(item, "type", None) != "message":
                    continue
                for c in getattr(item, "content", []) or []:
                    c_type = getattr(c, "type", None)
                    if c_type == "output_text":
                        text = getattr(c, "text", None)
                        if text:
                            parts.append(str(text))
                    elif c_type == "text":
                        text = getattr(c, "text", None)
                        if text:
                            parts.append(str(text))
                        else:
                            value = getattr(c, "value", None)
                            if value:
                                parts.append(str(value))
                    else:
                        text = getattr(c, "text", None)
                        value = getattr(c, "value", None)
                        if text:
                            parts.append(str(text))
                        elif value:
                            parts.append(str(value))
        except Exception:
            pass

        return "\n".join(p.strip() for p in parts if p and str(p).strip()).strip()

    def complete(self, deployment: ResolvedDeployment, model_input: list[dict[str, Any]]) -> ChatResult:
        try:
            resp = self.client.responses.create(model=deployment.model, input=model_input)
        except APIStatusError as e:
            raise ProviderExecutionError(self._error_info(deployment, e)) from e

        text = self._extract_output_text(resp)
        return ChatResult(
            text=text,
            provider_id=self.provider_def.id,
            deployment_id=deployment.id,
            model=deployment.model,
            raw=resp,
        )

    def stream_text(self, deployment: ResolvedDeployment, model_input: list[dict[str, Any]]) -> Iterator[str]:
        try:
            with self.client.responses.stream(model=deployment.model, input=model_input) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        yield event.delta
                    elif event.type == "response.refusal.delta":
                        yield event.delta
                    elif event.type == "response.error":
                        yield "\n[error]\n"
        except APIStatusError as e:
            raise ProviderExecutionError(self._error_info(deployment, e)) from e

    def list_models(self, provider: ProviderDef) -> list[ModelInfo]:
        items: list[ModelInfo] = []
        model_objs = self.client.models.list()

        for m in model_objs:
            mid = getattr(m, "id", None)
            if not mid:
                continue

            if _ALLOWED_MODEL_PREFIXES and not mid.startswith(_ALLOWED_MODEL_PREFIXES):
                continue

            meta = self.model_catalog.get(mid, {})

            items.append(
                ModelInfo(
                    id=mid,
                    provider_id=self.provider_def.id,
                    provider_type=self.provider_def.type,
                    vendor=meta.get("vendor", "OpenAI"),
                    display_name=meta.get("display_name", mid),
                    description=meta.get("description", ""),
                    created=getattr(m, "created", None),
                    owned_by=getattr(m, "owned_by", None),
                    input_cost_per_million=meta.get("input_cost_per_million"),
                    output_cost_per_million=meta.get("output_cost_per_million"),
                    context_window=meta.get("context_window"),
                    tags=tuple(meta.get("tags", []) or []),
                )
            )

        return items
```

What moved here from `main.py`:

- `client.responses.create(...)`
- `client.responses.stream(...)`
- `_extract_output_text(...)`
- OpenAI error normalization
- `client.models.list()`

That is the point.

---

# Step 6: wire provider registry into startup in `server/main.py`

Now change `server/main.py`.

## 6.1 Add imports

Near the top of `server/main.py`, change imports.

Remove:

```python
from openai import OpenAI, APIStatusError
from openai.types.responses import ResponseInputParam
```

Add:

```python
from .providers.registry import build_provider_registry
from .providers.types import ProviderExecutionError, ResolvedDeployment
```

Keep `ResponseInputParam` out. For 5A, treat `build_model_input()` output as ordinary list-of-dicts.

## 6.2 Add global registry

Near the global vars section, add:

```python
PROVIDER_REGISTRY = None
```

## 6.3 Update lifespan startup

Inside `lifespan(...)`, after `MODEL_CATALOG = load_model_catalog()`, add:

```python
global PROVIDER_REGISTRY
PROVIDER_REGISTRY = build_provider_registry(model_catalog=MODEL_CATALOG)
```

## 6.4 Delete the global OpenAI client

Delete this line entirely:

```python
client = OpenAI(api_key=oai_cfg.open_ai_apikey)
```

That is the symbolic and practical cut.

---

# Step 7: replace `/api/chat`

This is the first route migration.

## 7.1 Current behavior you must preserve

The route must still:

- create a conversation if needed
- self-heal file artifacts
- store the user message
- build context and `model_input`
- stream text back to the browser
- save assistant message to the DB

## 7.2 Replace the core body

Inside `/api/chat`, remove the cast to `ResponseInputParam` and replace the model/provider handling.

Use this shape:

```python
@app.post("/api/chat")
def chat(req: ChatRequest, model: str | None = None):
    cid = req.conversation_id or str(uuid.uuid4())
    if req.conversation_id is None:
        create_conversation(cid)

    heal = ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=5, include_global=False)
    if heal["created"]:
        print("self-heal artifacts: cid=%s heal=%s", cid, heal)

    full = postprocess_text(req.message)
    if full:
        add_message(cid, "user", full)

    model_input = build_model_input(cid, full)
    print("[debug] model_input:", json.dumps(model_input, indent=2)[:5000])

    requested_target = (req.model or model or MODEL).strip()
    target = PROVIDER_REGISTRY.resolve_chat_target(requested_target)
    provider = PROVIDER_REGISTRY.get_chat_provider(target)

    def gen():
        parts: list[str] = []
        try:
            for delta in provider.stream_text(target, model_input):
                parts.append(delta)
                yield delta

            assistant_text = postprocess_text("".join(parts))
            if assistant_text:
                add_message(
                    cid,
                    "assistant",
                    assistant_text,
                    meta={
                        "model": target.model,
                        "provider": target.provider_id,
                        "deployment_id": target.id,
                    },
                )
        except ProviderExecutionError as e:
            yield f"\n[server exception: {type(e).__name__}]"

    resp = StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
    resp.headers["X-Conversation-Id"] = cid
    return resp
```

That keeps the endpoint behavior stable while moving execution into the provider.

---

# Step 8: replace helper functions used by A/B recovery

Right now `_call_model()` and `call_model_with_recovery()` are OpenAI-specific.

We are keeping the recovery ladder, but changing what it calls.

## 8.1 Replace `_call_model`

Delete this old function:

```python
async def _call_model(model_name: str, model_input):
    loop = asyncio.get_running_loop()
    fn = partial(client.responses.create, model=model_name, input=model_input)
    return await loop.run_in_executor(None, fn)
```

Replace with this:

```python
async def _call_model(provider, deployment: ResolvedDeployment, model_input):
    loop = asyncio.get_running_loop()
    fn = partial(provider.complete, deployment, model_input)
    return await loop.run_in_executor(None, fn)
```

## 8.2 Delete OpenAI-only error helpers

Delete these from `main.py`:

- `_openai_error_payload`
- `_extract_err_msg`
- `_extract_output_text` if you copied it into the provider

Those now belong in `openai_provider.py`.

## 8.3 Update `call_model_with_recovery`

Change the function signature from:

```python
async def call_model_with_recovery(model: str, model_input: list[dict]) -> dict:
```

To:

```python
async def call_model_with_recovery(target: ResolvedDeployment, provider, model_input: list[dict]) -> dict:
```

Then replace its internals with this shape:

```python
async def call_model_with_recovery(target: ResolvedDeployment, provider, model_input: list[dict]) -> dict:
    attempts: list[tuple[str, list[dict], int]] = []

    attempts.append(("original", model_input, 0))
    attempts.append(("original_retry", model_input, 250))

    mi_noimg = _strip_images(model_input)
    attempts.append(("no_images", mi_noimg, 0))
    attempts.append(("no_images_retry", mi_noimg, 250))

    mi_textonly = _strip_file_messages(mi_noimg)
    attempts.append(("text_only", mi_textonly, 0))

    mi_trim = _trim_history(mi_textonly, keep_last_n=30)
    attempts.append(("trim30", mi_trim, 0))

    last_err = None

    for label, mi, backoff_ms in attempts:
        if backoff_ms:
            await _sleep_ms(backoff_ms)

        try:
            result = await _call_model(provider, target, mi)
            text = strip_zeitgeber_prefix(result.text or "")
            return {"ok": True, "text": text, "recovery": label}
        except ProviderExecutionError as e:
            info = e.info
            info.recovery_step = label
            last_err = {
                "provider": info.provider_id,
                "deployment_id": info.deployment_id,
                "model": info.model,
                "message": info.message,
                "status_code": info.status_code,
                "request_id": info.request_id,
                "provider_error_type": info.provider_error_type,
                "body": info.raw,
                "recovery_step": info.recovery_step,
            }

            if info.status_code and int(info.status_code) < 500:
                return {"ok": False, "error": last_err}

    return {
        "ok": False,
        "error": last_err or {
            "provider": target.provider_id,
            "deployment_id": target.id,
            "model": target.model,
            "message": "Unknown provider error",
            "status_code": 500,
            "body": {"error": {"message": "Unknown provider error"}},
        },
    }
```

Important: the response shape still looks close to the old one, so your UI should survive.

---

# Step 9: replace `/api/chat_ab`

Now move A/B to the new provider path.

## 9.1 Current behavior to preserve

This endpoint must still:

- create the conversation if needed
- store the user message
- run A and B in parallel
- preserve recovery metadata
- return structured payload with `a` and `b`

## 9.2 Resolve deployment targets separately

Inside `chat_ab()`, replace:

```python
model_a = (req.model_a or MODEL).strip()
model_b = (req.model_b or model_a).strip()
```

With:

```python
requested_a = (req.model_a or MODEL).strip()
requested_b = (req.model_b or requested_a).strip()

target_a = PROVIDER_REGISTRY.resolve_chat_target(requested_a)
target_b = PROVIDER_REGISTRY.resolve_chat_target(requested_b)

provider_a = PROVIDER_REGISTRY.get_chat_provider(target_a)
provider_b = PROVIDER_REGISTRY.get_chat_provider(target_b)
```

## 9.3 Update `run_one()` or remove it

Your current `run_one()` is OpenAI-shaped and can just go away.
Instead use `call_model_with_recovery()` directly.

Use this pattern:

```python
    a_res = None
    b_res = None
    async with anyio.create_task_group() as tg:
        async def run_a():
            nonlocal a_res
            a_res = await call_model_with_recovery(target_a, provider_a, model_input)

        async def run_b():
            nonlocal b_res
            b_res = await call_model_with_recovery(target_b, provider_b, model_input)

        tg.start_soon(run_a)
        tg.start_soon(run_b)
```

## 9.4 Preserve assistant message metadata

Wherever you later save A/B outputs, make sure their meta carries:

```python
{
    "model": target_a.model,
    "provider": target_a.provider_id,
    "deployment_id": target_a.id,
    "ab_group": ab_group,
    "slot": "A",
    ...
}
```

and same for B.

That provenance is one of the core goals of Phase 5.

---

# Step 10: replace `/api/models`

Now migrate the model listing route.

## 10.1 Keep the response shape stable

Do **not** redesign the frontend payload yet.
Return the same `{"models": [...]}` shape.

## 10.2 Replace the route body

In `/api/models`, remove the direct `client.models.list()` call and replace the route with this pattern:

```python
@app.get("/api/models")
def api_models():
    global _MODELS_CACHE, _MODELS_CACHE_TS

    now = time.time()
    if _MODELS_CACHE and (now - _MODELS_CACHE_TS) < _MODELS_TTL_SECONDS:
        return _MODELS_CACHE

    try:
        model_infos = PROVIDER_REGISTRY.list_models_for_default_provider()
        items: list[dict[str, Any]] = []

        for m in model_infos:
            items.append(
                {
                    "id": m.id,
                    "created": m.created,
                    "owned_by": m.owned_by,
                    "vendor": m.vendor,
                    "display_name": m.display_name,
                    "description": m.description,
                    "input_cost_per_million": m.input_cost_per_million,
                    "output_cost_per_million": m.output_cost_per_million,
                    "context_window": m.context_window,
                    "tags": list(m.tags),
                }
            )

        payload = {"models": items}
        _MODELS_CACHE = payload
        _MODELS_CACHE_TS = now
        return payload
    except Exception as e:
        if DEBUG_ERRORS:
            traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to list models: {e}")
```

Why “default provider” only?

Because 5A is not the UI maturity phase yet.
If you return three providers’ worth of raw options right now, the browser picker becomes nonsense.

---

# Step 11: what to leave alone

These things are **not** part of 5A.
Leave them alone unless they are directly broken by the refactor.

- `server/summary_helper.py`
- summary route internals
- embeddings provider flow
- vector backend code
- frontend dropdown semantics
- DB schema changes
- chat/project-level deployment persistence
- request-shape redesign

This is how you stop 5A from metastasizing.

---

# Step 12: exact smoke-test checklist

After you finish the code changes, test in this order.

## 12.1 App boots

Start the service.
Expected result: startup succeeds and `PROVIDER_REGISTRY` is created.

## 12.2 `/api/models`

Open the app or hit the endpoint.
Expected result: model list still appears in the UI exactly like before.

## 12.3 normal chat

Start a new chat and send a message.
Expected result:

- streaming still works
- assistant reply is stored
- assistant message meta includes:
  - `model`
  - `provider`
  - `deployment_id`

## 12.4 A/B chat

Run an A/B comparison.
Expected result:

- both responses still come back
- recovery still works
- metadata survives

## 12.5 raw model backward compatibility

Pick a raw model string in the current UI and send a message.
Expected result: it still works, because the registry converts it to an ephemeral deployment.

That last test is the one that tells you whether 5A landed cleanly.

---

# Step 13: what “done” means for 5A

Phase 5A is done when all of the following are true:

- `server/main.py` no longer directly calls `client.responses.stream(...)`
- `server/main.py` no longer directly calls `client.responses.create(...)` for chat/A-B
- `server/main.py` no longer directly calls `client.models.list()`
- `/api/chat` still streams
- `/api/chat_ab` still works
- `/api/models` still works for the current UI
- assistant message metadata now includes provider/deployment provenance
- no frontend changes were required

That is the end of 5A.
Not perfection. Not local providers yet. Just the real provider spine.

---

# Step 14: recommended commit order

Use this order exactly. It keeps breakage localized.

## Commit 1

Add:

- `server/providers/types.py`
- new `server/providers/base.py`

Do not touch `main.py` yet.

## Commit 2

Add provider/deployment loaders to `server/config.py`.
Do not wire them anywhere yet.

## Commit 3

Add `server/providers/openai_provider.py`.
Smoke-test import only.

## Commit 4

Add `server/providers/registry.py`.
Write a tiny local smoke test or temporary debug print if needed.

## Commit 5

Wire registry into `lifespan()` in `main.py`.
Do not switch routes yet.

## Commit 6

Switch `/api/models`.
Test it.
This is the safest route to migrate first.

## Commit 7

Switch `/api/chat`.
Test streaming.

## Commit 8

Switch `_call_model()`, `call_model_with_recovery()`, and `/api/chat_ab`.
Test A/B.

## Commit 9

Clean up dead OpenAI-only helpers left behind in `main.py`.

This sequence gives the highest velocity with the fewest mystery explosions.

---

# Step 15: the first TOML you should eventually support

You do not need to require this yet because the loaders synthesize defaults.
But this is the shape Phase 5 is moving toward:

```toml
[providers.openai]
type = "openai"
api_key = "${OPENAI_API_KEY}"
base_url = "https://api.openai.com/v1"

[deployments.chat_default]
provider = "openai"
model = "gpt-5.4"
display_name = "OpenAI Chat Default"
capabilities = ["chat", "stream", "catalog"]

[deployments.summary_default]
provider = "openai"
model = "gpt-5-mini"
display_name = "OpenAI Summary Default"
capabilities = ["chat"]
```

That is the seed format for Phase 5B and beyond.

---

# The blunt summary

Do not overcomplicate 5A.

This phase is:

- add types
- add interfaces
- add config loaders
- add registry
- move OpenAI chat/catalog into provider class
- keep UI compatible using ephemeral deployments for raw model strings

That gets you out of the OpenAI-welded state without detonating the rest of the app.

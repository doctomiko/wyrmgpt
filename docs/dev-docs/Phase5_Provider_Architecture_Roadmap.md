# WyrmGPT Phase 5: Provider Architecture and Grown-Up Model Selection

Checked against `WyrmGPT.20260314.c.zip` on March 15, 2026.

This document assumes the old retrieval/ingestion-heavy Phase 5 has been renamed to **Phase 6**.
This new **Phase 5** is the bigger move: make WyrmGPT stop being an OpenAI-shaped app with local scaffolding and start becoming a real model workbench with interchangeable backends, honest provenance, and model selection that behaves like an adult.

## The blunt thesis

This phase is worth doing.

Not because “multi-provider” sounds sexy on a roadmap slide, but because the current code has already reached the point where OpenAI-specific assumptions are starting to leak into everything important:

- chat transport
- streaming
- model listing
- model picker UX
- summarization calls
- provenance metadata
- request shaping
- future tool calling / vision / structured-output decisions

You already have the first seed of a provider architecture in the embeddings layer. The app should now finish what it started and make **providers, deployments, capabilities, and provenance** first-class concepts.

If this phase lands well, WyrmGPT becomes:

- less dependent on one vendor
- able to target OpenAI, LM Studio, and Ollama from one scaffold
- more honest about what each backend can and cannot do
- easier to extend later for tools, vision, structured output, reranking, and routing

If it lands badly, you get a fake abstraction, a giant dropdown of nonsense, and twice as many bugs. So this needs to be done deliberately.

## What the codebase looks like right now

This is the current reality in the repo snapshot, not design-doc mythology.

### What is already pointing in the right direction

- `config.toml` already has a `[providers.openai]` section.
- `config.py` already separates some config domains cleanly.
- `server/providers/base.py` exists.
- `server/providers/openai_embeddings.py` exists.
- embeddings already have a provider-ish seam.
- messages already store some provenance in `meta`, especially `model`.
- the UI already supports A/B and canonical-choice workflow.

### What is still very OpenAI-welded

- `server/main.py` creates a global OpenAI client and directly calls `client.responses.stream(...)` and `client.responses.create(...)`.
- `server/main.py` also owns `/api/models`, which calls `client.models.list()` directly.
- summary generation is still OpenAI-shaped.
- the current model picker assumes a flat list of model IDs, not provider-aware deployments.
- the UI stores `chatoss.modelA` and `chatoss.modelB` as raw model strings in local storage.
- `server/providers/base.py` only defines an `EmbeddingProvider` protocol, not chat/catalog abstractions.
- the app does not yet have a provider registry or capability registry.

That is the line between “good scaffolding” and “grown-up platform.”

## The desired end state

By the end of this phase, WyrmGPT should have these properties:

### 1. Provider is not the same thing as model

The app should understand the difference between:

- a **provider**: OpenAI, Ollama, LM Studio, or a future backend
- a **deployment**: a configured callable target under that provider
- a **model family / model id**: the raw provider-native identifier

Example:

- provider = `openai`
- deployment = `chat_remote_best`
- model = `gpt-5.4`

and separately:

- provider = `ollama_local`
- deployment = `chat_local_fast`
- model = `qwen3:8b`

Users should usually choose **deployments**, not raw provider model IDs.

### 2. Requests are Wyrm-native first, provider-native second

The app should build its own internal request object and then translate it to OpenAI, Ollama, or LM Studio.

That means OpenAI’s Responses API schema stops being the secret truth of the whole system.

### 3. Capabilities are explicit

Every deployment should declare and expose capabilities such as:

- `chat`
- `stream`
- `embeddings`
- `vision`
- `tools`
- `structured_output`
- `reasoning`
- `stateful_responses`
- `model_listing`

The app should not guess. It should know.

### 4. Provenance is stronger and more honest

Every assistant message and generated artifact should be able to say:

- which deployment produced it
- which provider handled it
- which raw model ID was used
- whether the response was streamed
- whether recovery/fallback logic was used
- whether local or remote backend was involved

### 5. Model selection becomes policy, not just a dropdown

The app should support:

- app-wide default deployments
- project-level default deployments
- chat-level overrides
- separate defaults for chat, summary/title, embeddings, and optionally vision/tool work
- A/B across different providers, not just different OpenAI model IDs

## Non-goals for this phase

This phase is ambitious enough. Do not let it become a religion.

Not the goal here:

- full hosted multi-user SaaS hardening
- plugin bazaar madness
- support for every provider under the sun
- perfect feature parity across all backends
- a total frontend rewrite
- a giant schema apocalypse unless justified

You do **not** need to solve every provider quirk. You need a spine strong enough to survive them.

## Architectural stance

The internal truth should be:

**Wyrm request -> provider adapter -> provider response -> Wyrm response**

Not:

**OpenAI request everywhere, plus increasingly desperate hacks for local backends**

That second path is how you end up with technical debt wearing a fake mustache and calling itself interoperability.

## The core concepts to add

### Provider

A provider is a backend family with a transport and behavior profile.

Examples:

- `openai`
- `ollama`
- `lmstudio`
- later maybe `vllm`, `openrouter`, `anthropic`, or custom internal targets

### Deployment

A deployment is a configured callable target used by the app.

A deployment has:

- a stable ID
- a provider reference
- a raw model ID
- capability flags
- optional tags
- optional purpose hints
- optional performance/cost metadata
- connection details inherited from the provider

### Capability

Capabilities are the contract between selection UI and execution logic.

At minimum:

- `chat`
- `stream`
- `embeddings`
- `vision`
- `tools`
- `structured_output`
- `reasoning`
- `stateful_responses`
- `catalog`

### Wyrm request / Wyrm response

A provider-neutral internal schema for request/response handling.

A request should be able to represent:

- system instructions
- message history
- text parts
- image/file references
- temperature/top_p/max output tokens when supported
- requested output mode
- tools/tool schema
- reasoning preference
- prior-response chaining if supported
- metadata useful for logging and provenance

A response should be able to represent:

- final text
- tool calls if any
- structured output payload if any
- raw provider metadata
- usage / token-ish accounting if available
- reasoning summary if available
- warnings / degraded behavior / fallback info

## Recommended config design

You already started moving config into TOML. Good. Lean into it.

Use TOML to declare both providers and deployments.

### Example

```toml
[providers.openai]
type = "openai"
api_key = "${OPENAI_API_KEY}"
base_url = "https://api.openai.com/v1"

[providers.ollama_local]
type = "ollama"
base_url = "http://127.0.0.1:11434/v1"
api_key = "ollama"

[providers.lmstudio_local]
type = "lmstudio"
base_url = "http://127.0.0.1:1234/v1"
api_key = "lm-studio"

[deployments.chat_remote_best]
provider = "openai"
model = "gpt-5.4"
capabilities = ["chat", "stream", "tools", "vision", "reasoning"]
tags = ["remote", "default", "premium"]

[deployments.chat_local_fast]
provider = "ollama_local"
model = "qwen3:8b"
capabilities = ["chat", "stream"]
tags = ["local", "fast"]

[deployments.chat_local_reasoning]
provider = "lmstudio_local"
model = "openai/gpt-oss-20b"
capabilities = ["chat", "stream", "reasoning", "stateful_responses"]
tags = ["local", "reasoning"]

[deployments.summary_default]
provider = "openai"
model = "gpt-5-mini"
capabilities = ["chat", "stream"]
purpose = "summary"

[deployments.embed_remote_default]
provider = "openai"
model = "text-embedding-3-large"
capabilities = ["embeddings"]
purpose = "embeddings"

[deployments.embed_local_default]
provider = "ollama_local"
model = "qwen3-embedding"
capabilities = ["embeddings"]
purpose = "embeddings"

[defaults]
chat_deployment = "chat_remote_best"
summary_deployment = "summary_default"
embedding_deployment = "embed_remote_default"
```

### Important rule

Do not try to infer everything from live provider discovery.

Discovery is useful, but **declared deployments** are the stable user-facing unit.

That way the user can name and curate what matters instead of scrolling through a vendor dump of model IDs.

## Recommended backend interfaces

Add or evolve the provider layer around these protocols.

### `ChatProvider`

Responsibilities:

- send sync completion request
- send streaming completion request
- report capability support
- optionally support stateful response chaining
- normalize errors into Wyrm-friendly format

### `EmbeddingProvider`

You already have the seed of this. Keep it, but move it under the same registry model.

Responsibilities:

- embed documents
- embed query
- surface vector dimensionality if known

### `ModelCatalogProvider`

Responsibilities:

- list raw models if the provider supports discovery
- annotate basic provider-side metadata
- do health checks if feasible

### `ProviderRegistry`

Responsibilities:

- load providers from config
- load deployments from config
- instantiate provider adapters lazily
- answer questions like “give me the deployment for summary work”
- validate that deployment capability requirements are met

### `DeploymentResolver`

Responsibilities:

- resolve app default vs project default vs chat override
- resolve A/B picks
- resolve fallback when a deployment is missing or unhealthy

## Recommended internal request shape

Keep it simple enough to build now.

```python
@dataclass
class WyrmMessagePart:
    type: str  # text | image_url | image_base64 | file_ref | json | tool_result
    text: str | None = None
    url: str | None = None
    media_type: str | None = None
    data: str | None = None
    meta: dict | None = None

@dataclass
class WyrmMessage:
    role: str  # system | user | assistant | tool
    parts: list[WyrmMessagePart]
    meta: dict | None = None

@dataclass
class WyrmChatRequest:
    deployment_id: str
    messages: list[WyrmMessage]
    stream: bool = True
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    tools: list[dict] | None = None
    response_format: dict | None = None
    reasoning: dict | None = None
    previous_response_id: str | None = None
    meta: dict | None = None
```

The point is not to invent a giant universal ontology. The point is to stop leaking provider-specific payloads across your app boundary.

## How model selection should work in the UI

The current flat model dropdown is not enough anymore.

A grown-up selector should have three layers.

### Layer 1: quick picks

For normal people, show a short curated list of favorite deployments.

Example:

- Remote Best
- Remote Cheap
- Local Fast
- Local Reasoning
- Local Vision

Each entry should show:

- label
- provider badge
- local/remote badge
- capability badges
- maybe rough cost or speed hints when known

### Layer 2: full deployment chooser

An expandable chooser for advanced users that can filter by:

- provider
- local vs remote
- supports vision
- supports tools
- supports structured output
- supports reasoning
- supports A/B

### Layer 3: defaults and policy

Settings pages should let the user pick defaults for:

- chat
- summary/title
- embeddings
- optional vision helper

Projects should be able to override the app default.
Chats should be able to override the project default.

### What should not happen

Do not dump raw model discovery from every backend into one giant unsorted dropdown. That is not freedom. That is clutter with a trench coat.

## Provenance and storage changes

Right now message `meta` often records `model`.
That is not enough anymore.

Store at least:

- `provider`
- `deployment_id`
- `model`
- `transport_family` (optional; e.g. `responses`, `chat_completions`, `ollama_native`)
- `streamed`
- `recovery`
- `base_url_alias` or connection label when useful

For embeddings and retrieval metadata, also store:

- `embedding_provider`
- `embedding_deployment_id`
- `embedding_model`
- vector dimensionality if available

This matters because later you are going to want to ask:

- which provider authored this conversation segment?
- which summary model created this artifact?
- which embedding backend built this semantic index?
- what changed when the user switched local models?

## File-by-file attack plan

This is the part that turns ambition into code.

### `server/providers/base.py`

Expand from a single `EmbeddingProvider` protocol into a real home for provider interfaces.

Add:

- `ChatProvider`
- `EmbeddingProvider` (existing, possibly adjusted)
- `ModelCatalogProvider`
- provider metadata/capability types
- normalized error/result types

### `server/providers/openai_embeddings.py`

Keep, but refactor to fit the registry pattern.

It should stop being a one-off and become the OpenAI embedding adapter behind the same provider plumbing as chat.

### New file: `server/providers/openai_chat.py`

Move OpenAI chat execution out of `main.py`.

Responsibilities:

- convert `WyrmChatRequest` to OpenAI Responses payload
- implement sync and streaming chat
- normalize OpenAI errors
- surface capabilities

### New file: `server/providers/openai_catalog.py`

Move `/api/models` provider-specific listing logic out of `main.py`.

Responsibilities:

- `client.models.list()` wrapping
- normalize discovered models
- optionally merge `server/model_catalog.json` annotations

### New file: `server/providers/ollama_chat.py`

First implementation can be either:

- a dedicated adapter, or
- a thin layer over a generic OpenAI-compatible adapter with Ollama quirk handling

Ollama should initially be treated as **non-stateful** for Responses-style chaining unless proven otherwise in real testing.

### New file: `server/providers/ollama_embeddings.py`

Add local embeddings support through Ollama.

This is strategically important because it unlocks fully local semantic retrieval.

### New file: `server/providers/lmstudio_chat.py`

Likely thin wrapper over a generic OpenAI-compatible transport with LM Studio capability quirks and stateful-responses support.

### New file: `server/providers/openai_compat.py`

This file is worth having.

Purpose:

- shared plumbing for backends that speak an OpenAI-shaped protocol
- centralizes base URL, auth header, request/response normalization, and compatibility quirks

This should be an adapter helper, not the internal truth of the whole app.

### New file: `server/provider_registry.py`

This becomes the backbone.

Responsibilities:

- load providers/deployments from config
- instantiate providers lazily
- validate deployment declarations
- answer selection and lookup questions

### `server/config.py`

Extend config loading to understand:

- declared providers
- declared deployments
- defaults
- project/chat selection overrides if you choose to store some defaults in config

Keep backward compatibility for a short migration window.

### `server/main.py`

This should get thinner.

The end goal is that `main.py` no longer knows how OpenAI works.

It should:

- resolve deployment selection
- build Wyrm request objects
- call the registry/provider layer
- stream provider-normalized events to the frontend
- store normalized provenance

This is the highest-value refactor in the whole phase.

### `server/summary_helper.py`

Stop hardcoding summary generation as an OpenAI-only call.
Use a summary deployment.

That gives the user freedom to keep premium chat but cheap summaries, or local summaries if they are patient.

### `server/context.py`

Keep this mostly provider-neutral.
Its job is building context, not caring who answers.

The only likely changes here are:

- build Wyrm-native message structures instead of provider-native payloads
- include deployment-aware metadata in debug surfaces where useful

### `server/query_retrieval.py`

Mostly unaffected, except for embedding-provider awareness and better provenance capture.

### `server/db.py`

Likely schema additions or migration support for:

- deployment ID on messages / summaries / artifacts
- provider ID on messages / summaries / embeddings
- chat/project preference fields evolving from raw model string to deployment ID

Do this carefully. Add columns before removing legacy assumptions.

### `server/static/app.js`

This is where the toy becomes an adult.

Needed changes:

- stop assuming `/api/models` returns the one true flat universe
- switch selector state from raw model ID to deployment ID
- support provider badges and capability badges
- allow A/B across deployments from different providers
- support app/project/chat default layers
- preserve old localStorage keys temporarily if you need migration

This file probably deserves targeted cleanup while you are in there, because it already contains some repeated A/B helper logic and model-picker assumptions.

### `server/static/index.html`

Likely light but meaningful changes:

- deployment selectors instead of model selectors
- optional badges / provider tags
- advanced chooser affordances
- defaults/settings surface

### `README.md` and docs

The docs need to stop saying “OpenAI models” as though that is the permanent center of gravity.

## API evolution

### Replace or supplement `/api/models`

The current `/api/models` is too narrow.

Add:

- `GET /api/providers`
- `GET /api/deployments`
- optionally `GET /api/deployments/health`

Keep `/api/models` temporarily if the frontend still uses it during migration.

### Update `/api/chat` and `/api/chat_ab`

They should accept deployment IDs instead of raw model IDs.

For a migration window, support both:

- `deployment_id`
- legacy `model`

If `model` is used, resolve it to the default OpenAI provider path and mark it as legacy in logs.

### Add policy-aware endpoints later if useful

Possible later additions:

- `POST /api/chat/route-preview`
- `GET /api/deployment-defaults`
- `POST /api/deployment-defaults`

Do not overbuild this on day one.

## Suggested workstreams

This is how I would sequence the phase.

## 5A — Provider spine

Deliverables:

- provider/deployment config model
- registry
- `ChatProvider` / `ModelCatalogProvider` / normalized result types
- OpenAI chat moved out of `main.py`

Definition of done:

- single-provider behavior still works
- `main.py` no longer directly performs OpenAI chat calls

## 5B — Deployment-aware model selection

Deliverables:

- `/api/deployments`
- frontend deployment picker
- deployment defaults for app / project / chat
- A/B works with deployments rather than raw models

Definition of done:

- users can choose named deployments, not just raw model IDs
- provenance stores deployment information

## 5C — Local backend bootstrap

Deliverables:

- Ollama chat adapter
- LM Studio chat adapter
- health/discovery path where feasible
- basic local-vs-remote badges in UI

Definition of done:

- at least one chat deployment from Ollama and one from LM Studio can answer through normal WyrmGPT chat flow

## 5D — Summary and embeddings decoupling

Deliverables:

- summary generation uses deployment resolver
- local embeddings option via Ollama or other local provider
- retrieval metadata captures deployment/provider provenance

Definition of done:

- chat, summary, and embeddings can each come from different deployments

## 5E — Capability-aware routing and degradation

Deliverables:

- capability flags enforced in selection UI and backend
- graceful fallback or refusal when a deployment cannot do vision/tools/structured output
- clearer error handling and debug visibility

Definition of done:

- the app does not pretend unsupported features exist
- capability mismatches are visible and recoverable

## 5F — Cleanup and truth pass

Deliverables:

- remove legacy raw-model assumptions where possible
- tighten docs
- migration cleanup
- log and provenance polish

Definition of done:

- provider layer feels native, not taped on

## Suggested schema and migration strategy

Do not rip out old fields early.

Safer sequence:

1. add deployment/provider columns
2. start writing both new and old metadata
3. update UI and APIs to prefer deployment IDs
4. backfill if helpful
5. remove old raw-model-only assumptions later

This keeps the app running while the interior organs are being rearranged.

## Risks and reality checks

### Risk 1: false abstraction

If you reduce everything to “OpenAI-compatible means same thing,” you will build a trap.

LM Studio and Ollama are useful targets, but they are not identical in behavior, especially around statefulness, reasoning output, structured output, tools, and input format edge cases.

### Risk 2: giant dropdown disease

If you expose raw discovered model IDs from every backend directly, the UI will become an equipment closet instead of a cockpit.

### Risk 3: provider parity fantasy

Some backends will not support everything. That is normal.

The right move is capability flags and graceful degradation, not pretending everybody can do everything.

### Risk 4: migration pain in `main.py`

A lot of app truth currently lives there. This phase will feel invasive. That is because it is.

### Risk 5: local backend performance expectations

Once you support local backends, the app needs to be honest about speed, memory cost, warmup delays, and context limits.

That is a UX problem as much as a backend problem.

## Why LM Studio and Ollama are worth targeting first

Because they are the most plausible local-backend complements to the scaffold you already built.

LM Studio is useful because it has leaned hard into an OpenAI-compatible `/v1/responses` path and, more recently, into the Open Responses spec, including streaming and stateful-response support in its local server story.

Ollama is useful because it has a large local-user footprint, practical embeddings, vision, structured output, and tool-calling support, even though its OpenAI-compat layer should be treated as a compatibility surface rather than your internal truth.

That combination makes them the right first local targets.

## Definition of success

This phase succeeds if, by the end:

- WyrmGPT chat is no longer hardwired to OpenAI inside `main.py`
- users select deployments, not just raw model strings
- A/B works across providers
- summaries and embeddings can use different backends than chat
- provenance records provider + deployment + model honestly
- LM Studio and Ollama can both be used from the normal chat scaffold
- unsupported features fail honestly instead of pretending

If you hit that, the app stops being a toy shell around one vendor and becomes a real scaffold.

## Final recommendation

Do it.

This is the right ambitious phase.

The old Phase 5 becoming Phase 6 makes sense because retrieval truth and ingestion richness are still important, but this provider/deployment refactor changes the shape of the whole project. It is the kind of thing that makes every later phase stronger if you do it early enough.

It will take real work.
It will probably get messy in the middle.
It is still the right move.

## Reference notes

This design was written against the repo snapshot above and informed by the current official docs for the first two serious local targets:

- LM Studio added OpenAI-compatible `/v1/responses` support in late 2025, including streaming, tool support, reasoning support, and stateful interaction via `previous_response_id`, and in January 2026 added Open Responses compatibility work and more `/v1/responses` improvements.
- Ollama documents OpenAI compatibility, tool calling, structured outputs, embeddings, and vision support, but its Responses compatibility should still be treated cautiously and validated in practice rather than assumed to be feature-identical to OpenAI.


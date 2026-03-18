# Connector Migration Plan: Moving the Best of Callie Connector Into WyrmGPT

## Purpose

This document describes how to migrate the durable, platform-agnostic strengths of the existing Callie Connector into WyrmGPT without turning WyrmGPT into a Discord-specific application. The core principle is simple: Discord should remain a transport and identity surface, while WyrmGPT becomes the conversation, retrieval, memory, and orchestration core.

The current connector already contains several valuable behaviors beyond simple message relay:

- rolling transcript summarization for long-running conversations
- memory suggestion workflows that propose durable facts for user review
- ambient and passive participation modes rather than only command-based operation
- conversation-state heuristics such as whether to speak, remain quiet, or continue listening
- durable message logging and transcript shaping for multi-user, long-running chat
- attachment handling and text extraction before model use
- policy-aware gating between invoked, passive, and ambient behavior

These are not inherently Discord features. They are conversation-orchestration features.

## What Should Move

### 1. Rolling conversation summaries

The connector compresses long transcript ranges into summaries once the raw history becomes unwieldy. This behavior should move into WyrmGPT as a first-class capability.

In WyrmGPT, summaries should not merely be a side table used to save tokens. They should become explicit artifacts or memory-adjacent objects with provenance.

Target behavior:

- recent turns remain available as hot raw transcript
- older turns are compressed into structured summaries
- summaries record source span, time range, and provenance
- summaries are available to retrieval and context-building logic
- summaries can themselves be revised, regenerated, promoted, or demoted

This differs from a simple token-saving hack. It becomes part of the conversation knowledge model.

### 2. Memory suggestions

The connector’s proposal-first memory workflow is worth keeping, but the implementation should mature. The public pattern is still good:

- the model notices something likely to matter later
- the system stores a pending suggestion rather than silently committing it
- the user reviews, accepts, edits, or rejects the suggestion

In WyrmGPT, this should become a proper queue of pending proposals rather than a text marker scraped out of assistant prose.

Target data shape for a pending proposal:

- title
- content
- rationale
- suggested scope
- significance or priority
- source conversation or message references
- status (pending, accepted, rejected, superseded)

### 3. Presence and reply-decision logic

The connector distinguishes between “allowed to speak” and “should speak.” That distinction should survive migration.

WyrmGPT should expose a conversation-presence engine that can return actions such as:

- reply
- remain quiet
- listen only
- summarize only
- suggest memory only
- request explicit invocation

Inputs should include:

- invocation state
- recent turn balance
- direct-address signals
- platform-supplied mention/reply context
- cooldown or chatter thresholds
- policy or venue rules
- identity metadata resolved by the edge adapter

The goal is to make the cognition core decide when participation is appropriate, instead of burying that logic inside one chat platform adapter.

### 4. Attachment ingestion and normalization

The connector already performs extraction and normalization for uploaded content. WyrmGPT should own this.

The edge adapter should submit files and metadata. WyrmGPT should decide whether those inputs become:

- inline content parts for immediate context
- durable files or artifacts for later retrieval
- both

This preserves one ingestion and artifact pipeline for every future client, not just Discord.

### 5. Durable session and transcript shaping

The connector does useful work around transcript construction, logging, and partial context shaping. Those lessons should influence WyrmGPT, but not every implementation detail should be copied blindly.

What belongs in WyrmGPT:

- durable turn storage with actor identity and provenance
- transcript export and summary generation
- source-aware context shaping
- explicit distinction between raw turns, summaries, memories, and artifacts

What should stay in the edge adapter:

- platform event parsing
- platform user and channel identifiers
- platform delivery retries and rate limits
- platform-specific mention semantics
- proxy identity resolution specific to the source platform

## What Should Stay Out of WyrmGPT

### Discord-specific policy and transport code

WyrmGPT should not directly care about guilds, channels, Discord webhooks, platform rate limits, or source-specific event shapes.

### Deep connector-style multi-tenancy

The connector needed true multi-guild behavior. WyrmGPT should avoid becoming tenant-native at the runtime level. That complexity belongs elsewhere.

### Ad hoc memory-blob stuffing as a permanent architecture

The connector’s memory blob strategy was a practical solution for direct model calls. In WyrmGPT, retrieval and scoped context selection should replace it over time.

## Recommended Migration Order

### Phase 1: Compatibility seam replacement

Goal: remove direct OpenAI dependency from the connector without rewriting the entire bot.

Add connector-facing endpoints to WyrmGPT:

- `POST /api/connector/respond`
- `POST /api/connector/summarize_block`
- `POST /api/connector/ingest_attachment`

The connector can then replace its provider-specific helper layer with WyrmGPT calls while leaving most of the surrounding bot behavior intact.

This is the lowest-risk path because it changes the seam, not the whole connector.

### Phase 2: Summary and attachment ownership

Goal: move durable transcript compression and artifact ingestion into WyrmGPT.

Actions:

- store summaries as first-class WyrmGPT objects
- route attachment ingestion through WyrmGPT
- record provenance and source references centrally
- begin shrinking duplicate storage responsibilities in the connector

### Phase 3: Memory suggestion queue

Goal: move proposed-memory logic into WyrmGPT and replace text-marker scraping.

Actions:

- add pending-memory tables or artifacts
- add review and approval APIs
- allow UI or admin tools to accept/reject/edit proposals
- preserve proposal provenance

### Phase 4: Presence engine

Goal: move “should reply / should listen / should stay quiet” from platform-specific heuristics into a reusable core service.

Actions:

- define a platform-neutral decision request schema
- let edge adapters contribute source metadata and invocation signals
- let WyrmGPT return recommended action and reason codes

### Phase 5: Connector slimming

Goal: turn the connector into a thin edge adapter.

By this stage, the connector should mainly do:

- source authentication and connection
- source event parsing
- identity resolution
- message delivery
- platform moderation hooks if needed

Everything else should be delegated to WyrmGPT.

## Proposed Connector-Facing API Surface

The exact request and response schema can evolve, but the target shape should be stable enough that multiple edge adapters can use it.

### `POST /api/connector/respond`

Expected inputs:

- source and venue metadata
- conversation or session identifier
- actor identity and display identity
- transcript window
- optional summaries or context hints
- attachment references or normalized parts
- system prompt identifier or prompt content
- requested deployment or capability hint

Expected outputs:

- assistant text
- action metadata
- response identifiers
- provenance or retrieval hints
- optional proposed memories

### `POST /api/connector/summarize_block`

Expected inputs:

- message block
- source span metadata
- optional summary policy

Expected outputs:

- summary text
- summary metadata
- optional artifact identifier

### `POST /api/connector/ingest_attachment`

Expected inputs:

- raw file or file reference
- source metadata
- actor metadata
- conversation link metadata

Expected outputs:

- normalized content parts for immediate use
- durable artifact or file identifiers
- extraction status and warnings

### `POST /api/connector/decide`

This may arrive later.

Expected inputs:

- latest event
- recent turn history
- invocation signals
- venue policy metadata
- adapter-resolved identity metadata

Expected outputs:

- recommended action
- confidence
- reason codes
- cooldown or retry hints

## Data Model Additions in WyrmGPT

The migration is easier if WyrmGPT introduces a few explicit concepts.

### Pending memory proposals

A durable queue for suggested memories.

### Conversation summary artifacts

Summary objects with provenance, source spans, and optional retrieval eligibility.

### External identity metadata

Separate fields for:

- visible actor identity
- authority identity
- source platform
- external message identifier
- venue identifier

This is useful for proxy or delegated identity systems and avoids coupling policy decisions to display names.

### Action decision records

Optional records for why the system chose to speak, stay quiet, or summarize.

These are useful for later debugging and future command-console inspection.

## Risks and How to Avoid Them

### Risk: WyrmGPT becomes Discord-shaped

Mitigation: keep edge adapters responsible for platform semantics. WyrmGPT should operate on source-neutral models.

### Risk: duplicate storage and summary pipelines linger too long

Mitigation: once WyrmGPT owns a workflow, make the connector stop owning the same durable responsibility.

### Risk: memory suggestions become magical and opaque

Mitigation: keep proposal-first workflow, provenance, and human review.

### Risk: presence logic becomes arbitrary or spooky

Mitigation: store reason codes and expose decision traces in admin tooling.

## Recommended Public Positioning

If this design is discussed in public docs, it should be framed as:

- WyrmGPT is the local-first cognition core
- edge adapters connect external platforms to the core
- summaries, memories, and artifacts are durable knowledge objects
- platform-specific code stays outside the core

That tells the truth without describing every private implementation trick.

## Immediate Next Steps

1. Add the three compatibility endpoints.
2. Replace the connector’s provider-specific helper layer with WyrmGPT calls.
3. Move summary ownership into WyrmGPT.
4. Add pending-memory proposal storage.
5. Design the decision API for reply/listen/quiet behavior.
6. Begin deleting duplicate logic from the connector as each capability graduates.

## Bottom Line

The correct migration path is not “merge the Discord bot into WyrmGPT.” The correct path is to promote WyrmGPT into the orchestration core and demote the connector into an adapter. That preserves the connector’s best ideas while keeping WyrmGPT platform-neutral and future-proof.

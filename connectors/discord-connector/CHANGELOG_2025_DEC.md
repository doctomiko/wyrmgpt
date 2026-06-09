# December 2025 Revision Summary
**Window:** 2025-12-18 → 2025-12-31  
**Theme:** Initial development (1 week); Refactor for correctness, identity safety, and maintainability (1 week)

---

## Major Refactors

### on_message Decomposition
- Extracted attachment handling into dedicated subroutines
- Extracted OpenAI request assembly into helper methods
- Reduced `on_message` complexity and side effects
- Centralized policy decisions (reply suppression, invocation checks)

### Attachment Pipeline Rewrite
- Fixed crashes caused by attachments in non-invoked messages
- Unified handling for:
  - images
  - PDFs
  - DOCX files
- Added graceful fallback paths for download and upload failures

---

## DOCX Support (Restored & Improved)
- Reintroduced DOCX parsing after rollback loss
- Features:
  - paragraph text extraction
  - basic Markdown-style formatting (bold/italic/underline)
  - table extraction into structured JSON
  - machine-readable document object injected into context
- Parsing failures fall back to file upload instead of aborting

---

## Configurability / Scalability

### Separate Global and Guild Configurations
- Introduced abstraction layer through ConfigManager class
- Ensured all objects that only need a single instance are singletons (Store, GlobalConfig, ConfigManager)
- Ensure GuildConfig maintains a cache that can fall back on .env vars in single-tenant made
- GuildConfig asserts that the guild_id may never be changed once assigned
- Store and underlying data now require guild_id for most records where it is sensible to do so
- Store implements a database cache to reduce DB reads

### Prevent Unintentional Log Leaking of Secrets
- All configuration classes support redaction of secrets such as "KEY", "TOKEN", "PASSWORD", etc.

---

## PluralKit / Proxy Identity Handling

### Reliable PK Resolution
- Added PluralKit API-based resolution by message ID
- Removed reliance on fragile embed/content heuristics
- Introduced caching to avoid API hammering

### Structured Identity Annotations
- Injected JSON-based `[SpeakerIdentity]` blocks into model context
- Explicit separation of:
  - conversational identity (proxy)
  - permission identity (Discord account)
- Prevented “identity doubling” in model perception

### Reply Policy Enforcement
- Replies reference proxy messages, not underlying accounts
- Suppressed @mentions of resolved Discord users
- Optional proxy-name prefix for clarity

---

## Context Enrichment

### Memories
- Commands provided for admins to add memories directly
- Chat bot can suggest memories to be added subject to moderator approval, and these have management commands also
- Context selcts the TOP x, BOTTOM y, and RAND(z) from the memory stack for any given chat reply - all configurable

### Summaries
- Summarization of messages too large to fit in context is done before the bot replies to a message. Therefore, some delays are considered normal.
- Summarized messages are no longer returned in context, but are retained for recordkeeping purposes.
- Commands have been added to allow admins to create summary of summaries, where context is particularly large.
- Summaries may be generated in batches, allowing for the clearing of back-logs.

---

## Ambient Mode & Suppression Fixes
- Fixed incorrect suppression of legitimate replies
- Unified logic for:
  - direct replies
  - leading @mentions
  - name-prefix pseudo replies
- Adopted fail-open behavior when Discord metadata is missing

---

## Stability & Graceful Failure
- Removed masked exceptions that silently broke behavior
- Reduced reconnect noise and clarified logging
- Ensured configuration omissions degrade safely

---

## Cleanup & Consistency
- Consolidated PK logic into dedicated helper module
- Reduced duplicated heuristics
- Improved internal documentation and naming consistency

---

## Known Follow-Ups (Post-December)
- Summarization interval audit and re-validation
- Optional PK-aware reply webhooks
- Context continuity improvements across long threads

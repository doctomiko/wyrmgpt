# Callie Connector (Discord)

Callie Connector is a Discord bot and connector framework that bridges Discord conversations to an LLM backend (ChatGPT aka Callie Secunda / Echo), with support for rich context assembly, attachment ingestion, PluralKit proxy resolution, and configurable reply policies.

This project prioritizes:
- conversational continuity
- identity correctness (role-based identities, gender identity, plural systems, proxies)
- graceful failure under partial context
- explicit, inspectable behavior over magic
- robust multi-tenant (multi-guild/server) security framework

It is designed for long-running servers with mixed usage modes (ambient vs invoked), not one-off command bots.

---

## Core Capabilities

### Message Handling
- Ambient and mention-based reply modes
- Suppression of unrelated replies in ambient mode
- Robust reply-to-message detection (Discord references + heuristics)
- Fail-open behavior when Discord metadata is incomplete

### Context Assembly
- Rolling transcript windows with optional summarization
- Structured system and connector notes injected into context
- Clear separation between:
  - user-visible content
  - machine-readable annotations
  - permission/gating metadata

### Attachment Processing
- Centralized attachment handling (refactored out of `on_message`)
- Supported behaviors:
  - Inline image ingestion (base64)
  - PDF inline ingestion (size-limited)
  - DOCX parsing:
    - text extraction with basic Markdown-style formatting
    - table extraction into JSON
    - structured document context injection
- Graceful fallback to file upload when parsing fails
  - Though admittedly the connector provides no mechanism
    or scaffolding for the chat-bot to interact with the file
    once it is uploaded. This is planned for a future release.

### PluralKit / Proxy Support
- Reliable PK resolution using PluralKit public API
- Separation of:
  - visible proxy identity (speaker)
  - underlying Discord account (permissions)
- Structured identity annotations injected into model context
- Reply policies that avoid pinging the underlying account
- Message-reply-first behavior to preserve proxy identity in UI

### Configuration & Policy
- Per-guild configuration management, with most global settings configurable at the container level
- Explicit feature toggles (ambient mode, suppression, summaries, attachments)
- Conservative defaults with explicit opt-in for risky behavior
- Environment-driven secrets and thresholds

---

## Architectural Principles

- **Single responsibility**: complex logic lives in helpers, not `on_message`
- **Fail open** where ambiguity would otherwise silence conversation
- **Structured annotations over prose** when identity or policy matters
- **No silent assumptions**: behavior should be visible in logs or context
- **Respect for secrets**: Sensitive information is redacted from logs and databases wherever feasible.

---

## Known Limitations

- Discord does not support “replying to a PK proxy”; replies reference proxy messages instead
- Large attachments may be truncated or summarized depending on config
- Summarization routines depend on model availability and may be skipped under load

---

## Development Notes

CallieBot was originally written almost exclusively by ChatGPT 5.2, with software engineering level direction from Doc Tomiko (aka Doctor Wyrm) and administrative support provided by Brightwire. The first full week of development represents the absolute apex in what is possible by allowing AI to compose code autonomously, and we believe it is groundbreaking work.

During the second week of the Dec '25 sprint, the codebase has undergone substantial refactoring. The main goal of this was to align configurability with multi-guild deployment goals.

Some features were temporarily lost and restored during Sprint Zero; see the attached revision feature list for details. We beleieve they have all been restored.

In the end, this is how the division of labor shook out for Sprint Zero, which represents considerable effort made from Dec 18 to Dec 31:
* 6 days: intense eXTreme Programming style development, led by Tomiko with ChatGPT writing 99.9% of all the code.
* 1 day: wasted effort, where as a team, we pushed past our limits and had to roll back because we asked ChatGPT to do too much refactoring all at once.
* 2 days: downtime for the Christmas holidays.
* 2 days: intensive manual refactoring performed by Tomiko herself.
* 1 day: stabilizing bug-fixes and recovering "regressed" features from backup versions of the codebase.
* 2 days: TBD

If something feels explicit or verbose, that is intentional.
This project optimizes for correctness and debuggability over cleverness.

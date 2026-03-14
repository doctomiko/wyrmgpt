# WyrmGPT Phase 3B + 3E Design Spec
## Personalization, Memory & Context Control Center
### With Forward Path Notes for 3C + 3D

Date: 2026-03-08  
Status: Design draft for implementation  
Authoring basis: current WyrmGPT architecture + follow-on discussion after 3A completion

---

## 1. Purpose

This document defines the design for combining **Phase 3B** and **Phase 3E** into a single coherent implementation pass.

The goal is to evolve the existing Memory & Context features into a mature control center that supports:

- curated personalization and instructions
- editable long-term memory
- scoped context controls
- future retrieval expansion
- future full-context assembly modes

This design deliberately avoids re-engineering the whole database where a cleaner incremental path already exists.

---

## 2. Summary of the Design Direction

The current split between "pins" and "memories" should remain, but their purpose must be clarified.

### Final conceptual split

**Pins** become:
- curated, prompt-visible, scoped personalization/instruction objects
- global or project-scoped
- manually created and edited
- stable, intentional, higher-authority context

**Memories** become:
- knowledge records used for retrieval and later matching
- user-created, user-edited, or system-generated
- searchable, rankable, editable, and chunkable
- lower-friction, more numerous, less inherently authoritative than pins

### Naming shift

The UI should stop implying that pins are just "manual memories."

Instead, the UI should present pins as:

- **Personalization**
- or **Instructions & Profile**

The preferred term for the section is:

**Personalization**

This better matches the intended feature set:
- nickname
- occupation
- about me
- style preferences
- instructions
- project-specific custom behavior

---

## 3. Why 3B and 3E Should Be Implemented Together

3B and 3E are tightly coupled because:

- the backend model of memory and personalization determines what the editor must show
- the editor must expose the metadata needed for better retrieval
- the retrieval/debug UI depends on the distinction between personalization vs memory
- future context assembly cannot be clean until these concepts are separated

Doing these separately would create churn and likely cause duplicated work.

---

## 4. Product Goals

The mature Personalization / Memory & Context system should allow the user to:

1. create, edit, delete, enable, disable, and scope personalization records
2. create, edit, delete, archive, and review memories
3. distinguish between user-asserted knowledge and system-inferred knowledge
4. control which context sources are searched
5. inspect what context was available vs what was actually used
6. maintain long-lived assistant continuity without hardcoding everything into system prompts
7. prepare the data model needed for richer retrieval and full-context modes later

---

## 5. Current Known Issues to Address

### 5.1 Previously saved memories are not being displayed in the current UI
This must be fixed as part of this pass.

The user must be able to:
- see previously saved memories
- edit them
- delete them
- inspect their metadata

This is not optional polish. It is core functionality.

### 5.2 The current UI language is misleading
The current model suggests:
- pins = manual
- memories = machine

This is too simplistic and will not scale.

### 5.3 Context controls are too scattered
The Memory & Context dialog should become the control center for:
- personalization
- memories
- context toggles
- retrieval/debug views

---

## 6. UI Architecture

## 6.1 Top-level access points

The Personalization / Memory & Context modal should be reachable from:

1. the **top menu / hamburger menu**
2. the **project right-click menu**

This reflects the fact that it is a workspace-level feature, not just a current-chat feature.

### Optional refinement
If the hamburger menu is being repurposed into a broader workspace menu, that is acceptable and consistent with this design.

---

## 6.2 Modal structure

The existing Memory & Context dialog should evolve into a larger, mature modal with tabbed or sectional navigation.

Recommended top-level sections:

1. **Personalization**
2. **Memories**
3. **Context**
4. **Corpus / Debug** (optional in first pass, but recommended)

---

## 6.3 Section: Personalization

This replaces the current "pins" concept in the UI.

### Purpose
Store scoped, curated, prompt-visible profile and instruction records.

### Display model
Show a scrollable list of personalization cards with:

- title
- type badge
- scope badge
- enabled/disabled state
- short preview
- edit button
- delete button

### Supported types
Initial supported `pin_kind` values:

- `profile`
- `style`
- `instruction`
- `preference`

These are intentionally broad enough to be useful and narrow enough to avoid becoming a junk drawer.

### Examples

#### profile
- Nickname: Vivian
- Occupation: videographer, webmaster
- About me: short personal profile
- Relationship to assistant identity continuity

#### style
- Prefer prose over headings
- Avoid emojis
- Be skeptical and candid
- Favor longer or shorter answers

#### instruction
- Always identify who is fronting if uncertain
- Use EST date/time in openings
- Project-specific editorial instruction
- How to address the user in this workspace

#### preference
- Preference for humor level
- Preference for directness
- Preference for formatting tendencies

### Personalization edit form
Fields:
- title
- type
- scope
- enabled
- body text
- structured values (optional future enhancement)
- sort order (optional but recommended)
- notes/provenance (optional read-only or editable metadata)

---

## 6.4 Section: Memories

This remains distinct from Personalization.

### Purpose
Store knowledge records for retrieval and continuity.

### Display model
Use a scrollable list of memory cards.

Each card should show:
- excerpt (2–5 lines, trimmed)
- scope badge
- origin/provenance badge
- tags
- importance
- pinned/archived status if applicable
- edit button
- delete button

### Memory editor panel
Selecting a memory should open a larger editor pane showing full details.

Fields:
- content
- scope
- tags
- importance
- archived
- origin/provenance
- created by
- source conversation (if any)
- source message (if any)
- created at / updated at
- save / delete actions

### Key requirement
The list must include already-saved memories from storage, not just newly created ones.

---

## 6.5 Section: Context

This section should contain controls for what the system may search and/or include.

Examples:
- search current project chats
- search global chats
- search files
- search memories
- include current transcript in full
- include other conversation summaries
- include personalization
- retrieval caps / limits (future)
- full mode / compact mode (future)

### Rule
Only settings that genuinely affect context assembly belong here.

Do **not** store purely application-side UI settings as prompt-visible pins.

---

## 6.6 Section: Corpus / Debug

This section can initially be minimal, but it should exist conceptually now.

Purpose:
- expose what sources were candidates
- show what was actually used
- show why an item was included
- show artifact/chunk counts
- show provenance
- support retrieval debugging

This paves the way for 3C and 3D.

---

## 7. Data Model

## 7.1 Keep the pins table, but redefine its meaning

The current pins table should be retained for incremental evolution.

It now represents **Personalization records**, not memory pinning.

### Recommended fields
Existing fields may remain as-is where possible, but the conceptual schema should become:

- `id`
- `scope_type` (`global` or `project`)
- `scope_id` (nullable for global)
- `pin_kind` (`profile`, `style`, `instruction`, `preference`)
- `title`
- `text`
- `value_json` (optional; for future structured settings)
- `sort_order` (optional)
- `is_enabled`
- `created_at`
- `updated_at`

### Notes
- `value_json` is optional but wise to include early if easy
- `sort_order` gives deterministic injection order
- `is_enabled` avoids destructive delete for temporary off states

---

## 7.2 Memories schema evolution

Memories should remain a separate concept.

### Recommended fields
- `id`
- `scope_type`
- `scope_id`
- `content`
- `tags_json`
- `importance`
- `archived`
- `origin_kind`
- `created_by`
- `source_conversation_id`
- `source_message_id`
- `created_at`
- `updated_at`

### Recommended values

#### `created_by`
- `user`
- `system`

#### `origin_kind`
- `user_asserted`
- `user_edited`
- `system_inferred`
- `system_summarized`
- `imported`

This is better than a simple boolean toggle.

It preserves:
- authorship
- provenance
- authority
- ranking usefulness
- debug transparency

---

## 7.3 Why not merge pins and memories now

Pins and memories serve different jobs:

### Pins / Personalization
- deliberate
- stable
- prompt-visible by default
- identity-shaping / behavior-shaping

### Memories
- retrievable
- evidence-bearing
- numerous
- editable knowledge objects
- not always included unless relevant

Merging them now would create confusion and complicate context assembly.

---

## 8. Context Assembly Rules

## 8.1 Personalization injection
Personalization records should be injected in a stable order.

Recommended order:
1. global enabled profile
2. global enabled style
3. global enabled instruction
4. global enabled preference
5. project enabled profile
6. project enabled style
7. project enabled instruction
8. project enabled preference

Alternative ordering is acceptable if project-specific items should override global ones later in the prompt.

### Important
Project scope should generally override global scope when conflicts occur.

---

## 8.2 Memory inclusion
Memories should not be blindly dumped in full.

They should be:
- retrieved
- ranked
- selected
- possibly expanded
- possibly summarized
- attached with provenance where useful

User-authored and user-edited memories should generally outrank system-inferred ones, all else equal.

---

## 9. Retrieval and Ranking Behavior

## 9.1 Personalization
Personalization is authoritative and deliberate.
It should normally be included directly when in scope and enabled.

## 9.2 Memories
Memories are part of the retrievable corpus.

Ranking priors should consider:
- scope match
- user vs system authorship
- origin kind
- importance
- tags
- recency
- explicit relevance

### Ranking guidance
Prefer, all else equal:
1. user_asserted
2. user_edited
3. imported
4. system_summarized
5. system_inferred

---

## 10. UI Behavior Details

## 10.1 Personalization list behavior
Each item should support:
- click to edit
- enable/disable
- delete
- scope badge
- type badge

### Nice-to-have later
- duplicate
- move between scopes
- drag reorder

---

## 10.2 Memory list behavior
Each item should support:
- click to edit
- delete
- archive/unarchive
- show excerpt
- show origin
- show tags
- show importance

### Nice-to-have later
- promote to verified
- convert into personalization
- move between scopes

---

## 10.3 Empty states
Use clear empty states.

Examples:
- "No personalization records yet."
- "No memories found for this scope."
- "Previously saved memories should appear here."

This matters because current confusion comes partly from silent emptiness.

---

## 10.4 Search and filter controls
Both Personalization and Memories should support filters.

Suggested filters:
- scope
- type
- enabled/disabled
- archived
- origin
- tag
- text search

---

## 11. API and Backend Behavior

## 11.1 Personalization endpoints
Retain the pins endpoint family if that is easiest, but reinterpret them as Personalization.

Suggested shape:
- `GET /api/memory/pins`
- `POST /api/memory/pins`
- `PUT /api/memory/pins/{id}`
- `DELETE /api/memory/pins/{id}`

Future rename to `/api/personalization` is acceptable, but not required now.

## 11.2 Memory endpoints
Need full CRUD, not just create.

Suggested minimum:
- `GET /api/memory`
- `POST /api/memory`
- `PUT /api/memory/{id}`
- `DELETE /api/memory/{id}`

Optional:
- archive toggle endpoint
- search/filter parameters
- scope filters

### Critical requirement
The GET endpoint must return previously saved memories for display.

---

## 12. Migration Strategy

## 12.1 Pins migration
Current pins data can likely be migrated in place with minimal disruption.

If needed:
- default `pin_kind = 'instruction'`
- default `scope_type` based on existing project association
- default `is_enabled = true`

## 12.2 Memory migration
Existing memories should gain default provenance values.

Suggested defaults:
- `created_by = 'system'` for existing machine-created records
- `origin_kind = 'system_inferred'` unless better source data exists

If user-created memories already exist, use:
- `created_by = 'user'`
- `origin_kind = 'user_asserted'`

## 12.3 UI migration
Rename labels gradually:
- "Pinned (manual)" -> "Personalization"
- "Long-term memory (machine)" -> "Memories"

---

## 13. Implementation Order

## 13.1 First pass
1. fix saved-memory display bug
2. rename pins UI to Personalization
3. add pin typing (`profile`, `style`, `instruction`, `preference`)
4. add scope + enabled state for personalization
5. add memory list loading and editing
6. add memory provenance fields
7. place context toggles into the same modal

## 13.2 Second pass
1. add filters/search
2. add better debug/corpus inspection
3. add structured `value_json`
4. improve ordering and override behavior
5. add convert/promote actions between memory and personalization

---

## 14. How This Paves the Way for 3C

3C is retrieval expansion beyond a single matched chunk.

This design prepares for that because:

- memories now have provenance and authority metadata
- personalization is clearly separated from retrievable knowledge
- the UI provides visibility into scope and origin
- future retrieval can decide whether to expand:
  - a memory
  - a full source item
  - a conversation window
  - a conversation summary
  - a file
- debug UI can show candidate vs chosen items

Without 3B + 3E cleanup, 3C would be harder to reason about and harder to debug.

---

## 15. How This Paves the Way for 3D

3D is about finalizing context assembly modes such as FULL / FILES / scoped inclusion rules.

This design prepares for that because:

- personalization becomes a stable injected layer
- memories become a ranked retrievable layer
- context toggles live in one control center
- the system can later define mode semantics such as:

### Example future mode behavior
- **FULL**:
  - include scoped personalization
  - include current conversation transcript in full
  - include selected retrieved memories expanded as needed
  - include project conversation summaries
  - include full files or file excerpts based on config

- **FILES**:
  - include scoped personalization
  - include files and file-derived retrieval
  - include memories only if explicitly enabled or matched
  - keep non-file chat history lighter unless requested

These rules become much easier to express once personalization and memory are separate concepts.

---

## 16. Non-Goals for This Pass

The following are not required to complete 3B + 3E:

- embedding-based retrieval overhaul
- aggressive reranking changes
- full tail-only rechunking optimization
- advanced cross-source orchestration
- full structured settings registry for every UI behavior
- perfect visual polish

Those can come later.

---

## 17. Final Position

The correct incremental path is:

- keep the pins table
- redefine it as Personalization
- give it typed, scoped, enabled records
- keep memories separate
- allow memories to be user-authored, user-edited, or system-generated
- make memory provenance explicit
- fix the saved-memory display gap
- centralize context controls in the same modal

This is the cleanest way to mature the product without ripping up the floorboards.

---

## 18. Immediate Build Checklist

### Must do now
- [ ] Fix memory list so previously saved memories display
- [ ] Add memory edit/delete capability
- [ ] Rename pins UI to Personalization
- [ ] Add `pin_kind`
- [ ] Add `is_enabled`
- [ ] Add scope-aware Personalization editing
- [ ] Add memory provenance fields
- [ ] Move context toggles into the same modal

### Good next
- [ ] Add filters/search
- [ ] Add corpus/debug tab
- [ ] Add stable personalization injection order
- [ ] Add ranking bias for user-authored memories

### Later
- [ ] Conversion flows between memory and personalization
- [ ] Retrieval expansion logic
- [ ] Mode semantics for 3D
- [ ] Structured JSON-backed personalization values

---
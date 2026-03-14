# WyrmGPT Phase 5 Roadmap

Code-checked against `WyrmGPT.20260313.d.zip` and reconciled with the current TODO docs on March 13, 2026.

This is the **real** Phase 5 roadmap, not the fantasy brochure version.

It assumes the following are already basically real enough to build on:

- local chat + project storage
- artifacting and chunking
- conversation transcript artifacts
- imported OpenAI history
- FTS retrieval
- hybrid/vector plumbing with local Qdrant + OpenAI embeddings
- personalization pins + memories
- A/B chat and canonical answer selection
- context preview/debug surface

The job of Phase 5 is **not** to rewrite the app from orbit.
The job is to make WyrmGPT more trustworthy, more useful, and more complete as a real personal knowledge cockpit.

---

## The blunt thesis

If I were steering this ship, I would **not** spend Phase 5 on shiny provider tourism, premature multi-user SaaS hardening, or six new backend abstractions for their own sake.

Phase 5 should focus on the things the current app is still weak at in day-to-day use:

1. ingestion truth for images, scanned PDFs, ZIP bundles, and URLs
2. retrieval truth for privacy boundaries and expansion behavior
3. current-world grounding through web retrieval
4. corpus control and inspection from the UI
5. operational polish so the whole thing stays maintainable after import scale increased massively

That is the straightest line from “cool scaffold” to “real working system.”

---

## What Phase 5 is for

Phase 5 should deliver four concrete outcomes:

### 1. WyrmGPT understands more of what you feed it
Right now text-heavy files work reasonably well, but screenshots, scanned PDFs, and ZIP archives are still second-class citizens.

### 2. WyrmGPT retrieves the right things more consistently
The app already retrieves a lot. The next step is making that retrieval more honest, more scoped, and less hand-wavy.

### 3. WyrmGPT can answer “what’s true now?”
Local canon is great. Reality outside the machine still exists. Web retrieval needs to become a real source, not a design-doc promise.

### 4. WyrmGPT becomes easier to operate and curate
Once the corpus gets big, the user needs better control over what is in it, what gets retrieved, and why.

---

## What should *not* be the center of Phase 5

These are real future items, but they should not dominate this phase:

- broad alternate chat provider support
- full local-LLM migration
- multi-user auth/productization as if this were already a hosted SaaS
- tool/plugin explosion
- major frontend rewrite
- heroic schema upheaval unless absolutely needed

Those are later problems. Some of them are Phase 6 problems. Some are “only if we actually need them” problems.

---

## Phase 5 structure

Phase 5 should have **five workstreams**, executed in this order.

---

# Workstream 5A — Retrieval Truth and Safety

## Why this comes first

Before adding more data sources, make sure retrieval scope and selection rules are honest.
Otherwise you are just making a larger, smarter mess.

## Problems this solves

- rough edges in private-vs-global transcript retrieval
- unfinished LLM expansion seam
- incomplete conversation-summary vs transcript policy
- lack of targeted conversation-window expansion
- retrieval behavior that is functional but still not fully transparent or predictable

## Code areas directly implicated

- `server/context.py`
- `server/query_retrieval.py`
- `server/db.py`
- existing TODO around transcript visibility in private projects (`server/db.py`)
- current disabled/placeholder expansion paths in retrieval code

## Deliverables

### 5A.1 Fix project privacy boundaries for retrieval
Make transcript retrieval obey project privacy rules cleanly and consistently.

That means:
- private project conversations do not leak into unrelated retrieval paths
- global projects can still contribute by design
- recent-conversation retrieval and transcript retrieval use the same rules, not two half-different truths

### 5A.2 Finish the “summary first, transcript second” policy
For other conversations in the same project, use summaries as the default lightweight recall path.
Escalate to transcript chunks only when retrieval actually justifies it.

This cuts noise and cost while improving relevance.

### 5A.3 Implement conversation-window expansion
Do not always escalate from a matching chunk to “include the whole transcript.”
Add a local chat-window expansion mode around the hit.

This is one of the highest-value quality upgrades in the whole roadmap.

### 5A.4 Either finish LLM query expansion or kill the fake seam
Right now the system can suggest that LLM expansion would help, but it does not really complete the loop.

Choose one:
- implement a real second-pass expansion flow, with config and debug truth
- or remove/disable the recommendation path until it is real

Do **not** keep the haunted half-feature.

### 5A.5 Make retrieval debug output fully honest
The context/debug panel should cleanly distinguish:
- scope resolution
- summary inclusion
- whole-asset inclusion
- raw retrieval hits
- expanded hits/windows
- final packed context

The user should be able to tell what happened without divination.

## Acceptance criteria

Phase 5A is done when:
- private project material cannot be made to bleed into unrelated contexts by accident
- project-other-conversation recall prefers summaries unless a transcript/window is justified
- retrieval can include a local conversation window around a hit
- query-expansion state is either real or gone
- the debug/context surface reflects retrieval truth without hand-waving

---

# Workstream 5B — Rich Ingestion: OCR, Scanned PDFs, ZIP Expansion, URLs

## Why this comes second

Now that retrieval rules are cleaner, broaden what can enter the corpus usefully.
This is the biggest “make the app actually smarter” move after Phase 5A.

## Problems this solves

- images are mostly just remembered as “an image exists”
- scanned PDFs are weak if `pypdf` cannot extract text
- ZIP files are shallow entry lists instead of real document bundles
- URL content is still more design ambition than normal user workflow

## Code areas directly implicated

- `server/artifactor.py`
- `server/image_helpers.py`
- `server/zip_helpers.py`
- file/URL artifact design docs
- upload endpoints in `server/main.py`

## Deliverables

### 5B.1 OCR pipeline for images and scanned PDFs
Add real text extraction for:
- screenshots
- photos of documents where practical
- image-only PDFs
- scanned PDFs with no useful embedded text

Minimum viable implementation:
- OCR text extraction
- confidence/provenance note in artifact metadata
- searchable artifact text produced from OCR output

Better version:
- optional caption/summary sidecar for images
- separate storage of raw OCR text vs user-facing artifact summary

### 5B.2 Proper image artifact metadata
For image uploads, store more than just placeholder text.
Add artifact metadata such as:
- image dimensions
- source filename
- OCR extracted text if present
- caption/description if generated
- provenance saying whether text came from OCR, captioning, or both

### 5B.3 Real ZIP decomposition
Finish the TODO in the artifactor so ZIP files can be treated as real bundles.

That means:
- optionally unpack ZIPs into a canonical internal folder
- artifact child files recursively
- maintain provenance to the parent ZIP
- expose the contents in UI/file management cleanly enough that it is not spooky

### 5B.4 URL ingestion as a first-class workflow
Add the ability to ingest a URL into the artifact pipeline deliberately, not as a weird side quest.

At minimum:
- “Add URL” UI path
- backend fetch + content normalization
- artifact text creation
- provenance stored as URL-derived

This should reuse the same chunking/index pipeline as files.

### 5B.5 Re-ingest / refresh semantics
For OCR’d files, ZIP children, and URLs, define a sane refresh/reingest behavior.
The user needs to know whether a refresh updates existing artifacts, creates new ones, or both.

## Acceptance criteria

Phase 5B is done when:
- screenshots and scanned PDFs become searchable text sources
- image uploads produce meaningful artifact text/metadata
- ZIP uploads can be expanded into searchable child content
- URLs can be intentionally ingested and searched like other artifacts
- provenance clearly says how content was extracted or fetched

---

# Workstream 5C — Web Retrieval That Actually Exists

## Why this is third

Do not bolt live web into a messy retrieval system. Do it after 5A and after URL ingestion from 5B has created some of the substrate.

## Problems this solves

- design docs promise web-aware grounding, but the live system mostly searches local canon
- current facts require outside tools or manual user feeding
- no coherent policy yet for ephemeral external truth vs saved canon

## Code areas directly implicated

- retrieval assembly in `server/context.py`
- ranking/merge behavior in `server/query_retrieval.py`
- artifacting pipeline if web results are cached as artifacts/chunks
- likely new web helper module(s)

## Deliverables

### 5C.1 Explicit web retrieval mode
Add a real retrieval mode for external results.
Prefer this to be deliberate and inspectable, not magical and uncontrollable.

Possible modes:
- off
- auto when query appears to need current-world knowledge
- always on for this prompt

### 5C.2 Cached web result artifacts with TTL
Treat web results as ephemeral corpus entries.
They should:
- be clearly labeled external
- store fetch time
- have a TTL / freshness policy
- be eligible for promotion into durable artifacts or memories later

### 5C.3 Merge internal and external results sanely
Internal canon and web results should not be shoved together without labels.

The retrieval layer should preserve provenance such as:
- internal memory/artifact/chat result
- external web result
- freshness timestamp
- score/rank origin

### 5C.4 UI truth for web use
The user should be able to see:
- whether web was used
- what sources were fetched
- which external chunks made final context
- whether anything was cached/promoted

### 5C.5 Recency/source quality policy
Even the first web implementation needs some quality rules.
At minimum:
- prefer reputable sources over sludge
- rank recent pages appropriately for current-events style questions
- avoid silently treating old cached web data as if it were live

## Acceptance criteria

Phase 5C is done when:
- the app can intentionally retrieve current external information during normal chat flow
- external chunks are cached and labeled distinctly from internal canon
- web use is visible in the context/debug surface
- freshness and provenance are not hidden from the user

---

# Workstream 5D — Corpus Control and Librarian UX

## Why this is fourth

Once you broaden ingestion and retrieval, the user needs better steering controls. Otherwise Phase 5 just creates a larger black box.

## Problems this solves

- chunk-level curation is still thin
- memory workflow is usable but not mature
- retrieval control surface lags behind retrieval substrate
- large imported corpora become hard to reason about

## Code areas directly implicated

- `server/static/app.js`
- `server/static/index.html`
- metadata editing endpoints in `server/main.py`
- persistence helpers in `server/db.py`

## Deliverables

### 5D.1 Chunk/source inspection UI
Let the user inspect retrieved chunks and source records more directly.

At minimum:
- source type
- source object reference
- chunk text
- tags
- significance / importance
- provenance
- retrieval channels (`fts`, `vector`, `web`, etc.)

### 5D.2 Exclude / demote / promote controls
The user needs light-weight editorial control.

Add the ability to:
- exclude a chunk or source from retrieval
- lower or raise significance
- promote web/file/chat-derived content into a more durable artifact or memory class

### 5D.3 Better memory management
Finish the missing grown-up memory operations:
- archive toggle
- pin/unpin clarity
- move/copy between scopes if you still want that behavior
- better filter/search
- clearer distinction between “behavior pin” and “retrievable fact memory”

### 5D.4 File/artifact management truth
Make it possible to see, from the UI:
- which files produced which artifacts
- which artifacts produced which chunks
- whether a file is stale, OCR’d, URL-derived, ZIP-expanded, or transcript-derived

### 5D.5 Operational repair actions
Useful buttons beat secret scripts.
Expose some safe maintenance actions in the UI or a visible admin panel, such as:
- refresh artifact text
- reindex artifact/chunks
- re-embed selected sources
- rebuild transcript for this conversation

## Acceptance criteria

Phase 5D is done when:
- users can inspect and edit retrieval-relevant metadata without cracking open SQLite
- memory/pin workflow feels deliberate instead of half-evolved
- file/artifact/chunk provenance is navigable in the UI
- common repair actions are no longer hidden behind script archaeology

---

# Workstream 5E — Operational Cleanup, Performance, and Packaging Truth

## Why this is last

Do this after the feature-bearing work, so cleanup reflects reality instead of an outdated guess.

## Problems this solves

- TODO/legacy seams still visible in core modules
- import scale is now much larger after full chat-history ingest
- indexing/embedding maintenance still leans heavily on scripts
- docs are in danger of drifting again

## Code areas directly implicated

- `server/db.py`
- `server/context.py`
- `server/artifactor.py`
- `server/query_retrieval.py`
- `server/static/app.js`
- scripts under `server/scripts/`
- README and docs

## Deliverables

### 5E.1 Clean out dead branches and compatibility cruft
Remove or quarantine clearly dead `if (False)` paths and stale fallback logic in hot-path modules.

Do not do this blindly. Do it after feature work lands.

### 5E.2 Make indexing/embedding maintenance more automatic
The system should rely less on “remember to run script X.”

Targets:
- incremental embedding refresh is reliable
- stale artifact/chunk state is detectable
- maintenance commands are documented and preferably surfaced in UI/admin tooling

### 5E.3 Performance pass on import/reindex/OCR pipelines
Now that corpus size has exploded, profile the real slow paths:
- import and re-import
- transcript refresh/reindex
- OCR ingestion
- ZIP expansion
- embedding rebuild/update

Optimize the ones that actually matter instead of cargo-cult tuning.

### 5E.4 Documentation truth pass
At the end of Phase 5, update:
- user guide
- architecture guide
- caveats / deployment notes
- import/export docs
- any README claims that have drifted

### 5E.5 Packaging and “average human install” honesty
Not necessarily a full installer yet, but move closer to a reproducible setup path.
At minimum:
- docs for optional OCR dependencies
- docs for vector backend expectations
- docs for web retrieval requirements and cautions

## Acceptance criteria

Phase 5E is done when:
- the hot-path modules are less haunted by obvious dead code
- maintenance of artifacts/chunks/embeddings feels more systematic
- large-corpus workflows are measurably less miserable
- docs once again match the real machine

---

## Recommended sequencing inside the phase

If you want this as a concrete build order rather than a theory lecture, do it like this:

### Milestone 1 — Retrieval honesty
Deliver 5A first.

This gives you:
- safer retrieval boundaries
- cleaner conversation recall
- better relevance per token
- less bullshit in the debug surface

### Milestone 2 — Rich ingestion
Deliver 5B next.

This gives you:
- screenshots and scans that finally matter
- ZIP bundles that stop being decorative
- URLs as real inputs instead of copied text blobs

### Milestone 3 — Live web grounding
Deliver 5C third.

This gives you:
- current-world truth when needed
- external retrieval with receipts
- a stronger answer to “why use this instead of the official UI?”

### Milestone 4 — Corpus librarian controls
Deliver 5D fourth.

This gives you:
- real editorial power over the corpus
- better repair/debug ergonomics
- less dependence on direct DB poking

### Milestone 5 — Cleanup and operational hardening
Deliver 5E last.

This gives you:
- a less cursed codebase
- easier ongoing maintenance
- docs that stop lying again

---

## A realistic “Phase 5 done” definition

You should consider Phase 5 complete when all of the following are true:

- private/global retrieval scope behaves predictably and visibly
- conversation recall uses summaries and local windows intelligently
- images, screenshots, and scanned PDFs can contribute searchable text
- ZIPs and URLs can become real searchable corpus content
- web retrieval can be used deliberately during ordinary chat
- the user can inspect and curate retrieval sources/chunks from the UI
- the app is less dependent on secret maintenance rituals
- the docs match what the code really does

If those are true, WyrmGPT has crossed from “promising local scaffold” into “serious personal knowledge system.”

---

## My recommendation on scope discipline

Here is the firm opinionated part.

Do **not** let Phase 5 turn into a junk drawer.

If a proposed task does not clearly advance one of these:
- retrieval truth
- richer ingestion
- live current-world grounding
- corpus control
- operational maintainability

then it probably does not belong in Phase 5.

That includes seductive side quests like broad provider tourism, grand tool ecosystems, or pretending this should already be a shared multi-user hosted product.

Make the machine better at knowing, retrieving, showing, and managing truth.
That is the right next move.

---

## Suggested Phase 5 epics, in short names

If you want ticket buckets or GitHub milestones, I would name them like this:

1. **P5A — Retrieval Truth**
2. **P5B — Rich Ingestion**
3. **P5C — Web Grounding**
4. **P5D — Corpus Librarian**
5. **P5E — Hardening and Cleanup**

That structure is clear, honest, and survives handoff better than cute names.

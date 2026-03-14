# WyrmGPT: What Is Not Done Yet

Checked against the actual code in `WyrmGPT.20260313.d.zip` on March 13, 2026.

This is not a wishlist copied from old design docs. This is the blunt version based on the code that is actually there.

## First, what *is* already real

Before I bitch about the gaps, credit where it is due.

The app already has:

- local chat storage
- projects and scoped files
- personalization pins and memories
- file artifacting
- conversation summaries
- conversation transcript artifacts
- corpus chunking and FTS search
- optional embedding/vector retrieval plumbing
- A/B chat with canonical answer selection
- a real context preview panel

So this is not “nothing works.” A lot works.

Now for the unfinished bits.

---

## 1. Live web retrieval is not actually part of the active RAG pipeline

The design docs talk about web as a first-class retrieval source.

The live code does not currently wire web search into normal context retrieval.

The active retrieval stack is built around local artifacts, corpus chunks, FTS, and optional vector search.

That means WyrmGPT is good at searching **your local material**, not at automatically pulling in current web facts during normal RAG.

---

## 2. LLM query expansion is only half-built

There is code and config for an “LLM expansion” idea.

But in the live retrieval code, that part only computes whether expansion would be **recommended**. It does not actually perform a second LLM-assisted expansion pass.

So right now this is more like a debug hint than a finished feature.

---

## 3. Image understanding is minimal

Uploaded images are artifacted as image references.

What is **not** there yet:

- OCR for text inside images
- captioning
- visual understanding for retrieval
- smart extraction from screenshots

In plain English: if an image matters, the app mostly knows that the image exists. It does not deeply understand it yet.

---

## 4. Scanned PDFs are not properly handled yet

PDF support depends on text extraction via `pypdf`.

If the PDF already contains text, fine.

If it is really a stack of scanned pages or image-only content, the app does not have a proper OCR pipeline in place. The code falls back to a placeholder when no extractable text is found.

So “PDF support” is real, but only for the text-bearing kind.

---

## 5. ZIP handling is still shallow

ZIP uploads are recognized, but the artifact content is basically an index of entries.

What is not done:

- automatic unpacking into searchable child files
- recursive artifacting of the contents
- treating the ZIP like a real document bundle

At the moment a ZIP is closer to “a catalog card” than “a fully ingested archive.”

---

## 6. Transcript indexing is useful but not yet elegant

Conversation transcript artifacts do refresh and reindex. That part is real.

But the code still has a placeholder-ish seam where transcript reindexing falls back to whole-artifact reindexing after refresh.

There is a hook for smarter tail-only re-chunking later, but it is not the active path yet.

So the transcript system works, but it is not the final optimized version.

---

## 7. Retrieval privacy boundaries still have rough edges

The code is trying to do the right thing with project visibility and chat-history retrieval.

But there is still an explicit TODO around whether recently updated conversations from private projects should be hidden from broader transcript retrieval.

Translated into human language: cross-conversation retrieval scoping is good, but not yet something I would call mathematically perfect.

If you care about strict separation, keep an eye on this and test it like you mean it.

---

## 8. Provider abstraction is not finished

The app structure hints at a future where more providers could exist.

The live implementation is still very OpenAI-centered.

Right now:

- chat is built around OpenAI Responses API
- embeddings are implemented only for OpenAI
- vector backend is implemented only for local Qdrant

The code even raises `NotImplementedError` for unsupported embedding providers or vector backends.

So yes, the architecture gestures toward flexibility. No, it is not provider-agnostic yet.

---

## 9. Embedding/vector retrieval is not fully automatic end-to-end

The app supports vector retrieval, but that does not mean every uploaded file automatically becomes embedded and searchable semantically with no extra work.

In practice, embedding/index maintenance still relies on the supporting scripts and the local vector store being set up correctly.

That means semantic retrieval is a supported subsystem, not yet a totally invisible “it just happens” background service.

---

## 10. No authentication, no multi-user safety net

This is still a local single-user tool.

There is no serious auth layer for exposing it publicly.

That is not a minor footnote. It means:

- do not throw it raw onto the public internet
- do not pretend it is multi-tenant SaaS-ready
- do not confuse “runs locally” with “hardened for hostile environments”

---

## 11. Chunk-level curation UI is not finished

The codebase has the bones for richer retrieval control, but the UI is not yet a full “corpus librarian” dashboard.

What users can already do:

- manage memories
- manage pins
- tune query settings
- inspect context/debug output

What is not really there yet in polished user-facing form:

- editing retrieval metadata on arbitrary corpus chunks
- excluding specific chunks from retrieval
- broad corpus maintenance from the UI
- clean promotion/demotion workflows for every source type

So the retrieval substrate is farther along than the retrieval control surface.

---

## 12. Some code cleanup debt is still plainly present

This repo is functional, but it is not pretending to be squeaky-clean.

You can see active cleanup debt in things like:

- TODO markers in frontend and backend
- old compatibility branches guarded by `if (False)`
- configuration comments that still mention pending refactors
- partial migration cruft from older schema versions

That does not mean the app is broken. It means the code is mid-flight rather than museum-ready.

---

## 13. A few design-doc promises are still ahead of reality

Some of the project docs describe a larger future system than the one running today.

The biggest examples are:

- web retrieval as a normal corpus source
- richer corpus curation semantics
- fuller provider abstraction
- more polished vector lifecycle management
- deeper file/ZIP/image handling

So the right posture is:

- trust the code more than the old docs
- treat the design docs as ambition, not gospel

---

## What I would call the highest-value unfinished work

If the goal is “make WyrmGPT meaningfully better for real use,” the most valuable unfinished items look like this:

1. real OCR/image understanding for uploaded images and scanned PDFs
2. actual live web retrieval integration
3. finishing LLM-assisted query expansion or killing it cleanly
4. stricter privacy/scoping behavior for cross-conversation retrieval
5. better automatic embedding/index maintenance
6. richer corpus-control UI for inspecting and curating retrieval sources

That is where the next serious lift probably pays off.

---

## Bottom line

WyrmGPT is already a functioning local scaffold with retrieval, personalization, and artifacting.

What it is **not** yet is a perfectly finished, fully provider-agnostic, OCR-capable, web-aware, privacy-tight, self-healing omniscient beast.

It has teeth already.

It just still has some gaps between them.


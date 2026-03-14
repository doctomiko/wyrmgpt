# WyrmGPT User Guide: Personalization, Artifacts, and RAG

Checked against the actual code in `WyrmGPT.20260313.d.zip` on March 13, 2026.

This guide is written for normal humans, not compiler goblins.

## What this part of WyrmGPT is trying to do

WyrmGPT is not just “a box that sends prompts to OpenAI.” It has its own local memory and filing cabinet.

Three pieces matter most if you want it to feel useful and consistent over time:

- **Personalization**: how the app knows who you are, how you like it to behave, and what should stay true across chats.
- **Artifacts**: the text copies and summaries WyrmGPT creates from files, memories, chat transcripts, and summaries so it can actually search them.
- **RAG**: short for retrieval-augmented generation. In plain English, this means the app can look things up from your own stuff before it answers.

If you use these three parts well, WyrmGPT becomes much more like a real working desk and much less like a goldfish with an API key.

---

## Personalization

### What personalization really is

In WyrmGPT, personalization comes from a few different layers that get stacked together.

At the broadest level, there is a **core system prompt** loaded from config. That is the baseline personality and behavior for the whole app.

On top of that, there are **Personalization** items you can edit in the UI:

- **About You**
- **Custom Instructions**
- **Memories**
- **Project settings** like a project prompt and whether that project is private or global

The code currently stores these in two different buckets:

- **Memory pins** for things like About You, instructions, style, and preferences
- **Memories** for longer-term facts and notes that are meant to be searchable

That split is a little nerdy under the hood, but as a user you can think of it like this:

- **Pins** shape behavior directly.
- **Memories** are facts and notes the app can retrieve later.

### About You

The **About You** section is for stable, useful facts such as:

- what you want to be called
- rough age range
- occupation
- enduring identity or context that helps future conversations

This is not the place for random daily noise. Put the stuff here that will still matter later.

Good examples:

- “Call me Doc.”
- “I’m a writer and software engineer.”
- “I prefer blunt answers over padded corporate politeness.”

Bad examples:

- “I had tacos for lunch.”
- “I’m annoyed today because Outlook is being cursed.”

### Custom Instructions

Use **Custom Instructions** for rules about how you want WyrmGPT to behave.

This is where you put things like:

- preferred tone
- how much detail you want
- whether it should challenge you or just help execute
- house rules for formatting or workflow

These instructions are treated as live guidance during context building. They are not just decoration.

### Memories

Use **Memories** for facts and conclusions you want WyrmGPT to be able to find later.

Each memory has:

- text
- tags
- strength/importance
- scope

#### What “strength” means

Strength controls how likely a memory is to matter.

- **0** = basically archived; it stays stored but does not actively participate in context
- **1–9** = retrievable memory
- **10** = effectively pinned and treated as very important

If something is core canon, a standing preference, or a decision you do not want lost, give it real weight.

#### Global vs project scope

Memories can be:

- **Global**: useful anywhere
- **Project-scoped**: only relevant inside one project

Use project scope for things like:

- novel canon
- codebase-specific rules
- one client’s preferences
- task-specific assumptions

Use global scope for things that follow you everywhere.

### Project prompt and project visibility

Each project can also have its own prompt and visibility.

- A **project prompt** adds extra instructions for that project.
- If **Override global/core prompt** is turned on, the project prompt replaces the normal core prompt instead of merely adding to it.
- A project can be **Private** or **Global**.

This matters because project visibility affects retrieval.

- **Private** means the project is meant to stay in its own lane.
- **Global** means that project can contribute to retrieval outside itself.

If you have one project that contains house canon and another that contains private journaling, do not casually set them both to global unless you want chaos.

### Best practices for personalization

Here is the practical version.

Use **About You** for stable identity and background.

Use **Custom Instructions** for behavior rules.

Use **Memories** for durable facts, decisions, and canon.

Use **project scope** when a fact only belongs to one domain.

Use **strength 10** sparingly, for the stuff that really deserves to elbow its way into context.

---

## Artifacts

### What an artifact is

An artifact is WyrmGPT’s local, normalized text representation of something it may want to search or include in context later.

Think of it as the app’s “working copy” of your material.

Artifacts can come from:

- uploaded files
- memories
- conversation summaries
- conversation transcripts

Why this exists: raw files and raw chat logs are awkward. The app needs a stable text form it can chunk, index, preview, and re-use.

### What happens when you upload a file

When you upload a file, WyrmGPT:

1. stores the file on disk under its scoped folder
2. registers it in the database
3. extracts usable text or a placeholder representation
4. stores that extracted content as an artifact
5. breaks the artifact into searchable chunks for the corpus index

For large artifacts, the extracted text may be stored in a sidecar file on disk instead of directly in a database field. That is a storage detail, not a user-facing feature.

### What file types are handled well right now

Based on the code as it exists now, WyrmGPT currently does a decent job with:

- plain text
- markdown
- source code and config files
- DOCX
- PDF files that already contain extractable text

### What file types are only partly handled

Some file types are only represented in a minimal way right now:

- **Images** are stored as image references, not deeply interpreted
- **ZIP files** are stored as a file listing, not fully unpacked into searchable contents
- **Scanned PDFs** or image-only PDFs do not get OCR; if `pypdf` cannot extract text, you mostly get a placeholder

So if you upload a screenshot full of text and expect the app to magically understand it, that is not where the live code is today.

### Conversation summaries and transcripts are artifacts too

WyrmGPT does not only artifact files.

It also creates artifacts for:

- **conversation summaries**
- **conversation transcripts**
- **memories**

That matters a lot.

A chat can become searchable later because the app keeps a transcript artifact and chunks it into the search index. Summaries also become searchable.

This is why using **Summarize** on a conversation is smart when a chat contains decisions or long-term useful work.

### How to get better results from artifacts

Give files good names.

Write file descriptions when they matter.

Prefer text-rich source material over screenshots when possible.

Use DOCX, markdown, text, or code files when you want the best extraction.

Summarize important chats instead of assuming the app will infer what mattered.

Keep projects organized so the right files are in the right scope.

---

## RAG

### What RAG is in this app

RAG means WyrmGPT can search your own material before sending the final prompt to the model.

In this codebase, RAG is not one single thing. It is a mix of two behaviors:

- **Wholesale inclusion**: include full memories, files, chat summaries, or chat transcripts directly in the prompt when configured to do so
- **Search-based retrieval**: search the chunk index and include the best matching pieces

So the app can either bring in whole documents, bring in matching snippets, or do both.

### What it searches

The current search stack is built on a local corpus index.

That index is made of chunks derived from artifacts. Those chunks can represent:

- file text
- memory artifacts
- conversation summaries
- conversation transcripts

The code supports:

- **FTS**: full-text search in SQLite
- **Embeddings**: vector search using OpenAI embeddings and a local Qdrant store
- **Hybrid**: combine both

### Important: vector search is optional, not magic by default

The code supports embeddings and Qdrant, but that does not mean every install is automatically fully embedded and ready to go.

The vector side depends on:

- embedding configuration
- a populated vector index
- the rebuild/indexing scripts having been run as needed

FTS is the simpler, more immediate part of the retrieval stack.

### Query settings control a lot

The Personalization modal includes **Query / Retrieval Settings**.

These let you decide whether the app should include or search things like:

- Full-Text Search
- Embeddings
- Chat Summaries
- Files
- Memories
- Chat Transcripts

It also lets you decide whether retrieval hits should expand into full artifacts or chat windows.

This is powerful. It is also easy to make stupid if you turn everything on blindly.

If context gets bloated, or the bot starts drowning in unrelated material, this is one of the first places to check.

### Search Chat History toggle

There is also a top-menu toggle for **Search Chat History**.

That affects whether conversation transcript retrieval is active beyond the immediate chat.

Turn it on when you want the app to reach back into prior conversations.

Turn it off when you want tighter isolation.

### The context panel is your friend

The right-hand **Context pack** panel shows what the app is about to send.

Use it.

Seriously. This is one of the strongest parts of the app.

If WyrmGPT seems confused, inspect the context panel before blaming the model. Often the problem is one of these:

- the right memory is not strong enough
- the wrong project is global
- retrieval settings are too broad or too narrow
- the file was not extracted the way you hoped
- the query is vague, so the search is vague

### How to get better RAG results

Be specific in your prompt. Concrete names beat vibes.

Use memory tags and meaningful memory text.

Keep important files in the right scope.

Summarize big chats that contain decisions.

Use project prompts and project memories for domain-specific work.

Inspect the context panel when results drift.

Re-upload or replace a file when the source changed significantly.

Prefer searchable text over screenshots.

### What RAG does **not** currently do

This matters because the design docs dream bigger than the live code.

As of this snapshot, WyrmGPT does **not** have live web retrieval wired into the retrieval pipeline.

It also does **not** do OCR or deep image understanding for uploaded image files.

And it does **not** unpack ZIP contents into a rich searchable subtree yet; ZIP files are indexed as listings.

---

## The short practical recipe

If you want WyrmGPT to work well, do this:

Put enduring personal facts in **About You**.

Put behavior rules in **Custom Instructions**.

Put durable facts and decisions in **Memories** with sane strength.

Use **project scope** for project-specific canon.

Upload text-friendly source files.

Use **Summarize** on important chats.

Keep an eye on **Query / Retrieval Settings**.

Check the **Context pack** panel when the bot acts like it licked a car battery.


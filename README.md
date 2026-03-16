# WyrmGPT

WyrmGPT is a tiny, local-first web UI (FastAPI + vanilla JS) for chatting with LLM models while keeping the *scaffold* under your control: conversations live in a local SQLite DB, chats can be organized into Projects, and you can A/B two models and pick which answer becomes “canonical” for future context.

This repo exists because the official web UI is… let’s say “enthusiastic about regressions.” If you’ve ever watched a feature you rely on quietly vanish between releases, you already understand the motivation.

We now support not only OpenAI API, but OpenAI-like services such as those running in LM Studio or Ollama. With locally hosted LLM, you can own your entire conversation with AI from end-to-end - model, scaffolding, history, and context.

## What you get

- A simple ChatGPT-style web UI you host locally
- Advanced A/B testing mode: send one prompt to two models, then click **Use** on the preferred answer to mark it canonical
- “Context pack” preview panel so you can see what the server is about to send to the model (system prompt + summary + memories + conversation history)
- Override or extend the system prompt at the project level.
- “Custom instructions” and weighted “memories” at the global and project level.
- Deployment (model) selection is populated from configured deployments in config.toml / config.secrets.toml, including OpenAI and local OpenAI-compatible providers such as LM Studio and Ollama. Optional UI metadata comes from `server/model_catalog.json`.
- Highly configurable RAG framework for files, memories, chat summaries, and chat transcripts - adjustable at both global and project levels. Now supports FTS and embeddings/vector db.
- Import complete chat history from OpenAI.

### Other cool things our app can do (so far)

Usability:
* The UI is super-fast and effecient. It will not bog down on long chat sessions that go on for days or weeks.
* Projects sidebar with expandable/collapsible conversation lists* 
* Unassigned chats stay in the main list; once assigned to a Project they disappear from the “All chats” list
* Project actions (right-click): New Chat, Edit description…, Make Global/Private, Add files, Manage Files…, Archive, Delete.
* Conversation actions (right-click): Rename, Suggest Title, Summarize, Move To…, Export Transcript, Archive, Delete. (Add Files for conversation is located near the chat input bar.)
* Chat navigation includes dynamic summaries and titles, so you have some clue what the chat was about.
* Can interpret MS Word (docx), PDF, markdown, various source code, and (on OpenAI models) image files.

Data sovereignty:
* Your chat history and files live on your computer. The only time that data leaves is if you send your chats to a cloud-based API. Local SQLite storage in `./data/callie_mvp.sqlite3`
* Add as many memories and files as you want. Set your own limits on how much data is sent to the LLM's context.
* Chat messages include a zeitgeber (time-giver) hint for the bot, so your AI assistant understands when you sent a specific message, even if the API doesn't support it.

Portability:
* You can export a Markdown transcript of any chat conversation.

Flexible scope:
* You can dynamically pick the LLM model(s) even mistream during your conversation.
* Move files between chat, project, and global scope easily.
* Declare a project as Global or Private () on the fly, at any time. For Global projects, conversations bits appear in RAG queries outside the project. In Private projects, conversations do not appear in RAG queries outside the project.
* Turn RAG search of global conversations on and off on the fly.

Transparency:
* We provide a cost table for the available models. Pick what works best for you.
* See exactly what is being sent to LLM context every time and even before you hit Send. 
* Chat with two different models at the same time and compare results. Heck, you can try talking to the same model in both A and B channels to see if it is variable.
* AB mode lets you decide which response is the one you want to keep in the canon conversation context. Change that at any time during your chat session.

### Lies We're Telling You

* “Average people can get this up and running” might be a lie today, but it doesn’t have to be a permanent lie. It may just be an ambition ahead of its packaging. There’s a difference between “this is easy” and “this can be made easy.” We took significant steps to make first time setup pretty mindless, but you should probably have some basic familiarity with command line tools like Python and optionally PowerShell.

* “We’re giving it away for free and won’t make money” is not a lie unless you’re quietly hoping never to confront the economics. If the project has to grow teeth eventually, better to admit that early. This project is source accessible for a reason. It isn't technically OSS, because we've seen a few dozen scammers out there with clones of ChatGPT, trying to grift the public as various models they loved got not-so-slowly phased out. We want this project to be accessible. That being said, we may monetize support, hosting, convenience, or advanced features later. We all need to eat. We are open to licensing what we've built to other entrepreneurs interested in leveraging it for their own ambitions - just be prepared to demonstrate that you're an honest dealer.

* And finally, it would be a lie if we didn't show you exactly where each reply comes from. That means: chat history (recent and historical), uploaded files, memories you input, and the model that was used in each particular interchange. Because of this, we do our best to show provenance on every assistant message. We show which model authored it, and whether the current responder is continuing a transcript partly authored by others. Users can decide whether they want “single-continuity assistant mode” or “strict per-model continuity mode.” One gives you the illusion of a single soul moving between bodies. The other gives you honest parallel minds. Both are useful. The lie is forcing one while pretending it’s the other.

## Quick start

Initial setup and optional steps have been updated and moved to the `_First_Time_Setup_All_Platforms.md` file in `./docs/` folder.

## How it works (high level)

- `server/main.py` is the FastAPI backend.
  - `POST /api/chat` streams responses through the provider/deployment registry using an OpenAI-compatible transport layer. That can target OpenAI, LM Studio, Ollama, and future compatible backends.
  - `POST /api/chat` streams responses using the OpenAI Responses API.
  - `POST /api/chat_ab` returns two simultaneous completions (A/B) and stores both with metadata.
  - `POST /api/ab/canonical` marks which A/B answer is canonical for future prompt context.

- `server/db.py` is the SQLite data layer and schema.

- `server/context.py` builds the “context pack”:
  - base system prompt (config.toml points to `system_prompt_file` or `default_system_prompt`)
  - pinned instructions and saved memories
  - conversation summary (if you generated one)
  - conversation history (with non-canonical A/B answers filtered out)

- `server/static/` contains the UI (`index.html`, `app.js`, `styles.css`).

## Using the UI

- **New** starts a fresh conversation.

- **Projects**
  - Click **+** to create a project.
  - Click a project header to expand/collapse its conversations.
  - Right-click a project header to rename/edit description.

- **Conversations**
  - Right-click a conversation to open the context menu:
    - Rename / Suggest Title
    - Move To… (assign to a Project)
    - Summarize (stores summary and appends it to context)
    - Archive / Delete

- **Model picker**
  - Pick “Model A” for normal chat.
  - Enable “Advanced A/B controls” from the chat menu to show Model B and use A/B mode.

- **A/B mode**
  - When Advanced is enabled and Model A != Model B, sending will call `POST /api/chat_ab`.
  - Click **Use** on the answer you prefer to mark it canonical (that’s what future context will include).

- **Context pack**
  - The right-side panel shows the exact prompt stack the server is assembling (system + pins + summary + history).
  - “Show more” increases how much is displayed (useful when debugging prompt drift or “why did it forget X?”).

## Data & backups

Your database is stored at:

- `./data/sql/wyrmgpt.sqlite3`

If you care about your chat history, back up the `data/` folder periodically. (SQLite WAL mode is enabled for better concurrency, so you may see `-wal` / `-shm` side files during runtime.)

## Model metadata (optional)

- the UI model selectors use `/api/deployments`
- `/api/models` is still used for metadata enrichment and provider model catalogs
- OpenAI model-prefix filtering (e.g. `gpt-`, `o1`, `o3`, `o4`) applies only to OpenAI provider catalog rows, not to local deployment choices.
- Pricing and context window data shown in the UI come from `server/model_catalog.json` when there is an exact key match for the deployment’s model.
  - You can hand-edit that file to add pricing/context-window notes shown in the UI.
  - There’s also an Open AI helper script at `server/scripts/sync_model_catalog.py` that can stub new entries from your account’s model list (it requires `OPENAI_API_KEY` to be set).

## API endpoints (selected)

- `POST /api/new` – create a new conversation
- `GET /api/conversations` – list conversations
- `POST /api/chat` – streaming chat (single model)
- `POST /api/chat_ab` – A/B chat (two models)
- `POST /api/ab/canonical` – choose canonical A/B answer
- `POST /api/conversations/{id}/summarize` – summarize a conversation
- `POST /api/conversations/{id}/project` – assign conversation to project
- `GET /api/projects` / `POST /api/projects` / `PUT /api/projects/{id}` – projects
- `GET /api/conversation/{id}/context` – context pack preview
- `GET /api/models` – list available models for dropdown
- `GET /api/deployments` – list configured deployments for the UI; supports `?capability=all` if you want the honest nerd version.

## Security note

This is a personal, local tool. There’s no authentication layer. Don’t expose it directly to the public internet unless you add proper auth and understand the risk (especially since it uses your OpenAI API key server-side).

## License

This project is licensed under the **PolyForm Noncommercial License 1.0.0** (see `LICENSE.md`). Noncommercial use is allowed with required notices; commercial use requires a separate agreement.

If you want a commercial license, contact the maintainers. We are reachable via https://doctorwyrm.com.
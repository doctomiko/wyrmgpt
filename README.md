# WyrmGPT

WyrmGPT is a tiny, local-first web UI (FastAPI + vanilla JS) for chatting with OpenAI models while keeping the *scaffold* under your control: conversations live in a local SQLite DB, chats can be organized into Projects, and you can A/B two models and pick which answer becomes “canonical” for future context.

This repo exists because the official web UI is… let’s say “enthusiastic about regressions.” If you’ve ever watched a feature you rely on quietly vanish between releases, you already understand the motivation.

## What you get

- A simple ChatGPT-style web UI you host locally
- A/B mode: send one prompt to two models, then click **Use** on the preferred answer to mark it canonical
- “Context pack” preview panel so you can see what the server is about to send to the model (system prompt + summary + memories + conversation history)
- Pinned “memory” notes (manual, user-curated)
- Model dropdown populated from your OpenAI account, with optional metadata from `server/model_catalog.json`

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

## Quick start

Prereqs:
- Python 3.10+ recommended
- An OpenAI API key

1) Create a virtualenv and install deps.

In PowerShell from the project root folder:

```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1

# Update PIP
pip install -U pip
#.\.venv\Scripts\pip.exe install -U pip

# Use the included PowerShell to and requirements.txt to install requirements to the venv:
. Install-Requirements.ps1
```

Or in Linux style container:

```bash
python -m venv .venv
source .venv/bin/activate

# Update PIP
pip install -U pip
pip install `<insert requires.txt here separated by spaces`>
```

Create your .env file in the repo root (see .env.example for the latest known-good settings):

```bash
# Required setting:
OPENAI_API_KEY=your_key_here

# Optional settings: 
# Model defaults
OPENAI_MODEL=gpt-5.4
OPENAI_TITLE_MODEL=gpt-5-mini
SUMMARY_MODEL=gpt-5-mini

# Load a system prompt from a file (the repo includes system_prompt.txt)
SYSTEM_PROMPT_FILE=.\\prompts\\system_prompt.txt

# Show server exception details (dev only)
DEBUG_MODE=true
```

Use the included PowerShell to start the server:

```powershell
. ./Start-Service.ps1
```

This activates the venv and runs the server like below in one step.

The relevant comment in Linux is:

```bash
uvicorn server.main:app --reload --port 8000
```

Open the UI:

In a browser on the same machine, go to the website.

[http://127.0.0.1:8000](http://127.0.0.1:8000)

## How it works (high level)

- `server/main.py` is the FastAPI backend.
  - `POST /api/chat` streams responses using the OpenAI Responses API.
  - `POST /api/chat_ab` returns two completions (A/B) and stores both with metadata.
  - `POST /api/ab/canonical` marks which A/B answer is canonical for future prompt context.

- `server/db.py` is the SQLite data layer and schema.

- `server/context.py` builds the “context pack”:
  - base system prompt (env `SYSTEM_PROMPT_FILE` or `SYSTEM_PROMPT`)
  - pinned memories
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

- `./data/callie_mvp.sqlite3`

If you care about your chat history, back up the `data/` folder periodically. (SQLite WAL mode is enabled for better concurrency, so you may see `-wal` / `-shm` side files during runtime.)

## Model metadata (optional)

- The model dropdown is populated from `client.models.list()` and filtered to IDs starting with:
  - `gpt-`, `o1`, `o3`, `o4`

- WyrmGPT also loads optional extra metadata from:
  - `server/model_catalog.json`

You can hand-edit that file to add pricing/context-window notes shown in the UI.

There’s also a helper script at `server/scripts/sync_model_catalog.py` that can stub new entries from your account’s model list (it requires `OPENAI_API_KEY` to be set).

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

## Security note

This is a personal, local tool. There’s no authentication layer. Don’t expose it directly to the public internet unless you add proper auth and understand the risk (especially since it uses your OpenAI API key server-side).

## License

This project is licensed under the **PolyForm Noncommercial License 1.0.0** (see `LICENSE.md`). Noncommercial use is allowed with required notices; commercial use requires a separate agreement.

If you want a commercial license, contact the maintainers (add your preferred contact info here).
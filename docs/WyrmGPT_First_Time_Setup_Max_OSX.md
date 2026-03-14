# WyrmGPT First-Time Setup Guide for macOS

This guide is for someone who has **never installed WyrmGPT before** and wants to go from:

**“I downloaded the repo”**

to:

**“My exported ChatGPT/OpenAI history is imported and embeddings have been built.”**

This is written for a normal Mac user, not a Python swamp wizard.

---

## What you are doing, in plain English

You are setting up a local web app on your Mac.

That app will:

- store your chats and files in a local SQLite database
- let you use OpenAI models through your own API key
- import your exported ChatGPT history from OpenAI
- build embeddings so WyrmGPT can search your past history more intelligently

---

## Important reality check before you start

This repo snapshot is still **Windows-first**.

That does **not** mean it cannot run on a Mac. It can. But it does mean two things:

1. The helper scripts in the repo are PowerShell scripts (`.ps1`), which are mainly for Windows.
2. The shipped `config.toml` uses Windows-style backslashes in several file paths.

So on Mac, you should assume this setup is **manual**.

That is why this guide tells you to:

- use **Terminal**
- use **python3**
- create a small `config.secrets.toml` override with Mac-friendly forward-slash paths

That is the sane path.

---

## Before you start

You need these things:

1. A Mac.
2. An internet connection.
3. An OpenAI API key.
4. Your exported ChatGPT data as a `.zip` file, or an extracted export folder.
5. About 10–20 minutes of setup time, plus however long your import and embedding build takes.

---

## Step 1: Install Python on your Mac

Do **not** trust whatever antique Python Apple may or may not have lying around.
Use a current Python 3 release.

The easiest beginner route is:

1. Go to the official Python downloads page.
2. Download the current **macOS installer**.
3. Run the installer.
4. When it finishes, open a new Terminal window.

Then test it:

```bash
python3 --version
```

If that prints a Python 3 version number, you are good.

Also test pip:

```bash
python3 -m pip --version
```

If both of those work, you can move on.

---

## Step 2: Download the WyrmGPT repo

You can do this either with Git or by downloading a ZIP.

For a beginner, the ZIP route is easier:

1. Download the WyrmGPT repository ZIP.
2. Extract it somewhere sensible, like:

```text
/Users/YourName/Documents/WyrmGPT
```

Do **not** leave it buried inside Downloads forever.
Put it somewhere you can find again.

If Git is already your thing, you can clone instead.

---

## Step 3: Open Terminal in the WyrmGPT folder

Open **Terminal**.

Then `cd` into the folder you extracted.

Example:

```bash
cd ~/Documents/WyrmGPT
```

You should now be standing in the folder that contains files like:

- `README.md`
- `requirements.txt`
- `config.toml`
- `server/`
- `prompts/`

---

## Step 4: Create the Python virtual environment

This creates a private Python sandbox just for WyrmGPT.

Run:

```bash
python3 -m venv .venv
```

That will create a `.venv` folder in the repo.

Activate it:

```bash
source .venv/bin/activate
```

Once activated, your prompt usually changes to show `(.venv)` at the front.

---

## Step 5: Install WyrmGPT’s Python packages

The repo includes `Install-Requirements.ps1`, but that is the Windows helper.
On Mac, just install directly from `requirements.txt`.

Run:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

That installs the major pieces WyrmGPT needs, including:

- FastAPI
- Uvicorn
- OpenAI SDK
- pypdf
- python-docx
- qdrant-client
- tiktoken
- python-dotenv

If that step fails, stop there and fix the package error before doing anything else.

---

## Step 6: Create a Mac-friendly `config.secrets.toml`

This is the part that matters most on macOS.

The repo’s `config.toml` currently uses Windows-style paths like:

```text
.\prompts\callie3rd_prompt.txt
```

On Mac, that is not a path you should trust.

So create a new file in the repo root called:

```text
config.secrets.toml
```

Put this in it:

```toml
[providers.openai]
api_key = "YOUR_OPENAI_API_KEY_HERE"
model = "gpt-5.4"
summary_model = "gpt-5-mini"

[core]
system_prompt_file = "./prompts/callie3rd_prompt.txt"

[summary]
summary_conversation_prompt_file = "./prompts/_summary_convo_prompt.txt"

[query]
filler_words_file = "./FTS filler+stop words.txt"

[embeddings]
cache_dir = "./data/embedding_cache"

[vector]
local_path = "./data/qdrant"
```

Replace `YOUR_OPENAI_API_KEY_HERE` with your real key.

Why this matters:

- it stores your API key in the intended secrets file
- it overrides the Windows-style paths with Mac-safe paths
- it prevents weirdness like vectors being written into bizarre backslash-named folders

You do **not** need to edit Python files.

---

## Step 7: Start WyrmGPT once

There is no Mac-native launcher script in this repo snapshot, so on Mac you launch the server directly.

From the repo root, with the virtual environment active, run:

```bash
python -m uvicorn server.main:app --reload --port 8000
```

If it starts cleanly, open a browser and go to:

```text
http://127.0.0.1:8000
```

If the page loads, the app is alive.

To stop the server later, press:

```text
Ctrl+C
```

---

## Step 8: Export your ChatGPT data from OpenAI

You need your exported history before WyrmGPT can import it.

In ChatGPT, request a data export.

The current OpenAI help flow is:

1. Sign in to ChatGPT.
2. Click your profile icon.
3. Open **Settings**.
4. Open **Data Controls**.
5. Choose **Export Data**.
6. Confirm the export.

The download link is sent by email and expires after 24 hours.

Download that ZIP file somewhere you can find it.

Example:

```text
/Users/YourName/Downloads/chatgpt-export.zip
```

You can leave it as a ZIP file.
The importer supports either:

- the ZIP itself, or
- an already-extracted export folder

---

## Step 9: Import your exported OpenAI data into WyrmGPT

Back in Terminal, from the WyrmGPT repo folder, do a **small test first**.

Example:

```bash
python server/scripts/import_openai.py "/Users/YourName/Downloads/chatgpt-export.zip" --limit 10
```

That imports only 10 conversations so you can catch obvious nonsense before you throw the whole archive at it.

If that looks good, do the real import:

```bash
python server/scripts/import_openai.py "/Users/YourName/Downloads/chatgpt-export.zip" --refresh-transcripts --reindex --ingest-root-files
```

### What those flags mean

- `--refresh-transcripts` = rebuild transcript artifacts for imported conversations
- `--reindex` = build/update the searchable text index after import
- `--ingest-root-files` = import matching root-level export assets when present

### Important notes

- If your path has spaces, keep the whole path in quotes.
- The importer creates a log file under:

```text
data/import_logs/
```

- Imported conversation IDs are prefixed with `oaiexport-` by default.
- The importer can also preserve metadata from the export, not just transcript text.

---

## Step 10: Build embeddings

Once the import has finished and reindexing is done, build embeddings.

Run:

```bash
python server/scripts/rebuild_embeddings.py
```

This script:

- finds corpus chunks that do not yet have embeddings
- calls the OpenAI embeddings API
- stores vectors in the local Qdrant-backed vector store under `data/qdrant`
- updates embedding state in the local database

This is the step that turns your imported history into something semantic retrieval can use.

In normal human terms: this is what helps WyrmGPT find things by meaning, not just by exact keyword.

---

## Step 11: Start the app again and use it

If the server is not already running, start it again:

```bash
source .venv/bin/activate
python -m uvicorn server.main:app --reload --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

At this point you should have:

- the app running locally
- your imported OpenAI chat history in the database
- transcript artifacts generated
- the text index built
- embeddings built for retrieval

---

## Where your data lives

WyrmGPT stores its local working data in the repo’s `data` folder.

The important locations are:

```text
data/callie_mvp.sqlite3
```

This is the main SQLite database.

```text
data/qdrant/
```

This is the local vector store used for embeddings.

```text
data/embedding_cache/
```

This is the embedding cache.

```text
data/import_logs/
```

This stores importer log files.

If you care about your work, back up the `data` folder.

---

## The shortest possible command list

If you already understand what you are doing, this is the no-nonsense version:

```bash
cd ~/path/to/WyrmGPT
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create `config.secrets.toml`:

```toml
[providers.openai]
api_key = "YOUR_OPENAI_API_KEY_HERE"
model = "gpt-5.4"
summary_model = "gpt-5-mini"

[core]
system_prompt_file = "./prompts/callie3rd_prompt.txt"

[summary]
summary_conversation_prompt_file = "./prompts/_summary_convo_prompt.txt"

[query]
filler_words_file = "./FTS filler+stop words.txt"

[embeddings]
cache_dir = "./data/embedding_cache"

[vector]
local_path = "./data/qdrant"
```

Run the app once:

```bash
python -m uvicorn server.main:app --reload --port 8000
```

Import a small test:

```bash
python server/scripts/import_openai.py "/Users/YourName/Downloads/chatgpt-export.zip" --limit 10
```

Do the real import:

```bash
python server/scripts/import_openai.py "/Users/YourName/Downloads/chatgpt-export.zip" --refresh-transcripts --reindex --ingest-root-files
```

Build embeddings:

```bash
python server/scripts/rebuild_embeddings.py
```

Start the app again:

```bash
python -m uvicorn server.main:app --reload --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

---

## Troubleshooting

### `python3: command not found`

Python is either not installed or not installed correctly.

Fix: install current Python from the official macOS installer, then open a fresh Terminal window and try again.

### `pip` or package install errors

Make sure your virtual environment is activated:

```bash
source .venv/bin/activate
```

Then try:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### The app starts, but it seems to ignore the prompt files or path-based settings

This is the classic Mac path problem.

Fix: check that your `config.secrets.toml` uses forward slashes like this:

```toml
[core]
system_prompt_file = "./prompts/callie3rd_prompt.txt"
```

Do **not** use Windows backslashes in that override.

### The import command fails on a path with spaces

Put the path in quotes.

Correct:

```bash
python server/scripts/import_openai.py "/Users/YourName/My Files/chatgpt export.zip"
```

### Embeddings fail immediately

Usually this means one of these:

- your API key is missing
- your API key is wrong
- your API account does not have billing/usage set up for embeddings
- your internet connection is down

Check `config.secrets.toml` first.

### The app starts, but your imported chats do not seem searchable

Make sure you actually ran both:

1. the import with `--reindex`
2. `rebuild_embeddings.py`

Without those, you may have imported data but not built the search structures that make retrieval good.

---

## Recommended first-run workflow

If you want the least painful path, do it in this order:

1. Install Python.
2. Download and extract WyrmGPT.
3. Create `.venv`.
4. Activate it.
5. Install `requirements.txt`.
6. Create `config.secrets.toml` with your API key and Mac-friendly paths.
7. Start the app once and confirm `http://127.0.0.1:8000` loads.
8. Request and download your ChatGPT export.
9. Run a small import test with `--limit 10`.
10. Run the full import with `--refresh-transcripts --reindex --ingest-root-files`.
11. Run `rebuild_embeddings.py`.
12. Start the app again and use it.

That is the sane path on Mac.

Not glamorous, but sane.

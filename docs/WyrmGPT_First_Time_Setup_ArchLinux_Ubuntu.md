# WyrmGPT First-Time Setup Guide for Arch Linux and Ubuntu

This guide is for someone who has **never installed WyrmGPT before** and wants to go from:

**“I downloaded the repo”**

to:

**“My exported ChatGPT/OpenAI history is imported and embeddings have been built.”**

This is written for a normal Linux user, not a Python cryptid.

---

## What you are doing, in plain English

You are setting up a local web app on your Linux machine.

That app will:

- store your chats and files in a local SQLite database
- let you use OpenAI models through your own API key
- import your exported ChatGPT history from OpenAI
- build embeddings so WyrmGPT can search your past history more intelligently

---

## Important reality check before you start

This repo snapshot is still **Windows-first**.

That does **not** mean it cannot run on Linux. It can. But it does mean three things:

1. The helper scripts in the repo are PowerShell scripts (`.ps1`), which are mainly for Windows.
2. The shipped `config.toml` uses Windows-style backslashes in several file paths.
3. On Linux, the sane path is to do the setup manually in a terminal.

So this guide tells you to:

- use your normal Linux terminal
- create a Python virtual environment
- install the requirements with `pip`
- create a small `config.secrets.toml` override with Linux-safe forward-slash paths

That is the clean route.

---

## Before you start

You need these things:

1. A Linux computer running either **Ubuntu** or **Arch Linux**.
2. An internet connection.
3. An OpenAI API key.
4. Your exported ChatGPT data as a `.zip` file, or an extracted export folder.
5. About 10–20 minutes of setup time, plus however long your import and embedding build takes.

---

## Step 1: Install Python and a few basic tools

Pick the section for your distro.

### Ubuntu

Open a terminal and run:

```bash
sudo apt update
sudo apt install -y python3-full python3-pip python-is-python3 git unzip
```

Why these:

- `python3-full` gives you a fuller Python install, including virtual environment support
- `python3-pip` gives you pip
- `python-is-python3` makes `python` point to Python 3, which is convenient for this repo
- `git` and `unzip` are just practical

### Arch Linux

Open a terminal and run:

```bash
sudo pacman -Syu --needed python python-pip git unzip
```

Why these:

- `python` gives you Python 3
- `python-pip` gives you pip tooling
- `git` and `unzip` are practical

### Test that Python works

Now test it:

```bash
python --version
python -m pip --version
```

If those both print version numbers, you are good.

If `python` fails but `python3` works, use `python3` everywhere this guide says `python`.

---

## Step 2: Download the WyrmGPT repo

You can do this either with Git or by downloading a ZIP.

For a beginner, downloading the ZIP is usually easier.

Put it somewhere sensible, such as:

```text
~/WyrmGPT
```

If you downloaded a ZIP of the repo, extract it.

If you prefer Git, you can clone instead.

Example:

```bash
git clone YOUR_REPO_URL_HERE ~/WyrmGPT
```

If you used the ZIP route, your file manager can extract it, or you can use:

```bash
unzip ~/Downloads/WyrmGPT.zip -d ~/
```

---

## Step 3: Open a terminal in the WyrmGPT folder

Change into the repo directory.

Example:

```bash
cd ~/WyrmGPT
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
python -m venv .venv
```

That creates a `.venv` folder inside the repo.

Activate it:

```bash
source .venv/bin/activate
```

Once activated, your prompt usually changes to show `(.venv)` at the front.

---

## Step 5: Install WyrmGPT’s Python packages

The repo includes `Install-Requirements.ps1`, but that is the Windows helper.
On Linux, just install directly from `requirements.txt`.

Run:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

That installs the core things WyrmGPT needs, including:

- FastAPI
- Uvicorn
- OpenAI SDK
- pypdf
- python-docx
- qdrant-client
- tiktoken
- python-dotenv

If this step fails, fix that first. Do not just keep plowing forward like a raccoon with a screwdriver.

---

## Step 6: Create a Linux-friendly `config.secrets.toml`

This matters more than it should.

The repo’s `config.toml` currently uses Windows-style paths like:

```text
.\prompts\callie3rd_prompt.txt
```

On Linux, do **not** rely on those.

Create a new file in the repo root called:

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
- it overrides the Windows-style paths with Linux-safe paths
- it prevents stupid path weirdness later

You do **not** need to edit Python source files.

---

## Step 7: Start WyrmGPT once

There is no Linux-native launcher script in this repo snapshot, so on Linux you launch the server directly.

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
~/Downloads/chatgpt-export.zip
```

You can leave it as a ZIP file.
The importer supports either:

- the ZIP itself, or
- an already-extracted export folder

---

## Step 9: Import your exported OpenAI data into WyrmGPT

Back in the terminal, from the WyrmGPT repo folder, do a **small test first**.

Example:

```bash
python server/scripts/import_openai.py "~/Downloads/chatgpt-export.zip" --limit 10
```

A safer version that always expands `~` correctly is:

```bash
python server/scripts/import_openai.py "$HOME/Downloads/chatgpt-export.zip" --limit 10
```

That imports only 10 conversations so you can catch obvious nonsense before you feed the whole archive into the machine.

If that looks good, do the real import:

```bash
python server/scripts/import_openai.py "$HOME/Downloads/chatgpt-export.zip" --refresh-transcripts --reindex --ingest-root-files
```

### What those flags mean

- `--refresh-transcripts` = rebuild transcript artifacts for imported conversations
- `--reindex` = build or update the searchable text index after import
- `--ingest-root-files` = import matching root-level export assets when present

### Important notes

- If your path has spaces, keep the whole path in quotes.
- The importer creates a log file under:

```text
data/import_logs/
```

- Imported conversation IDs are prefixed with `oaiexport-` by default.
- The importer supports either a ZIP file or an extracted export directory.

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

In human terms: this is what helps WyrmGPT find things by meaning, not just exact keyword.

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

If you already understand what you are doing, this is the no-nonsense version.

### Ubuntu

```bash
sudo apt update
sudo apt install -y python3-full python3-pip python-is-python3 git unzip
cd ~/WyrmGPT
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Arch Linux

```bash
sudo pacman -Syu --needed python python-pip git unzip
cd ~/WyrmGPT
python -m venv .venv
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
python server/scripts/import_openai.py "$HOME/Downloads/chatgpt-export.zip" --limit 10
```

Do the real import:

```bash
python server/scripts/import_openai.py "$HOME/Downloads/chatgpt-export.zip" --refresh-transcripts --reindex --ingest-root-files
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

### `python: command not found`

On Ubuntu, either install `python-is-python3` or use `python3` instead of `python`.

On Arch, make sure the `python` package is installed.

### `No module named venv`

On Ubuntu, install `python3-full`.

On Arch, make sure the normal `python` package is installed.

### `pip` or package install errors

Make sure your virtual environment is activated:

```bash
source .venv/bin/activate
```

Then try again:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### The app starts, but it seems to ignore the prompt files or other path-based settings

This is the Linux version of the Windows-path problem.

Fix: check that your `config.secrets.toml` uses forward slashes like this:

```toml
[core]
system_prompt_file = "./prompts/callie3rd_prompt.txt"
```

### The import command cannot find the export ZIP

Do not quote `~` and expect the shell to expand it inside quotes. Use a full path or use `$HOME`.

Good:

```bash
python server/scripts/import_openai.py "$HOME/Downloads/chatgpt-export.zip" --limit 10
```

Also good:

```bash
python server/scripts/import_openai.py /home/yourname/Downloads/chatgpt-export.zip --limit 10
```

Bad:

```bash
python server/scripts/import_openai.py "~/Downloads/chatgpt-export.zip" --limit 10
```

That looks nice and fails like a little gremlin.

---

## Final sanity check

If everything worked, you now have:

- Python installed
- a virtual environment for WyrmGPT
- WyrmGPT dependencies installed
- a valid `config.secrets.toml`
- the server running locally
- your ChatGPT export imported
- transcript artifacts rebuilt
- the search index rebuilt
- embeddings built

That means you have gone from **repo download** to **searchable imported history with embeddings**.

Which is, frankly, pretty decent for a first pass.

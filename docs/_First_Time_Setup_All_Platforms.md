# WyrmGPT First-Time Setup Guide (Windows, Mac, Ubuntu, and Arch Linux)

This guide is for someone who has never installed WyrmGPT before and wants to go from:

**“I downloaded the repo”**

to:

**“My exported ChatGPT history is imported and embeddings are built.”**

This version is deliberately simpler than the earlier per-OS drafts.
It keeps the steps that matter and cuts the throat-clearing.

If you know what you're doing in Python, skip to `The shortest possible version` at the end of this document.

---

## What I checked in this repo snapshot first

This install guide was checked against the code and config in `WyrmGPT.20260314.a.zip` before writing.

The important findings:

- `config.toml` **has** been adjusted to use forward slashes. Good. That is the right move for cross-platform sanity.
- `README.md` still talks about `.env` / `.env.example`, which is stale compared to the current TOML-based config loader in `server/config.py`.
- For a first-time civilian install, the safest path is: **leave `config.toml` alone** and create a small `config.secrets.toml` with your API key.

So this guide is built around the path that is least likely to waste the user’s afternoon.

---

## Before you start

You need:

- An Internet connection  (Duh!)
- Python 3 installed https://www.python.org/
- The WyrmGPT repo folder on your machine https://github.com/doctomiko/wyrmgpt
- An OpenAI API key (See https://platform.openai.com/api-keys)
- A terminal: PowerShell on Windows, Terminal on Mac, or a normal shell on Linux
- Your exported ChatGPT data from OpenAI, downloaded as a `.zip` file, or an extracted export folder.
- About 15 minutes of setup time, plus however long your import and embedding build takes.

You do **not** need to edit Python source code.
This version should greatly streamline initial configuration on Linux and Mac.

---

## Step 1: Download the WyrmGPT repo onto your machine

Download the ZIP and extract it somewhere you can find again, or clone it with Git.

For a beginner, the ZIP route is easier.

Good examples:

- Windows: `C:\Users\YourName\Documents\WyrmGPT`
- Mac: `~/Documents/WyrmGPT`
- Linux: `~/WyrmGPT`

Do **not** leave it buried inside your `Downloads` folder forever. Put it somewhere you can find again.

**Pro-tip**: Python is a programming language. It does not create executable binaries. As such, you can and should make a folder like X:\Repo or X:\RunPortable to store projects that pull source code from Git and/or do not have MSI Installer dependencies.

Then open a terminal in that folder.

**Pro-tip**: On Windows, right-click the folder and choose **Open in Terminal** or launch PowerShell from the Start meny then navigate using `cd` to the WyrmGPT folder. On Mac, use the Terminal app. On Linux, any shell (including SSH) should be fine.

You should be standing in the folder that contains:

- `README.md`
- `requirements.txt`
- `config.toml`
- `config.secrets.toml.example`
- `server/`
- `prompts/`

---

## Step 2: Install Python

### Windows

1. Go to the Python website. https://www.python.org/
2. Download a current Python 3 installer. We tested on **Python 3.11 or newer**.
3. Run it. (Note you may need to do this in Administrator mode.)
4. **Important**: Make sure you enable **Add Python to PATH** during install.
5. To update the PATH, you may need to restart Windows after installation is finished.

After that, test it in **PowerShell** Terminal:

```powershell
py --version
```

**Pro-tip**: You can right-click any folder and choose Run in Terminal to load Powershell at that location.

If that prints a Python 3 version, you are good.

**Important**: Note that some installations will prefer "py" instead of "python" or vice-versa. If `py` does not work but `python` does, use `python` in the commands below.

### Mac

1. Go to the Python website. https://www.python.org/
2. Download a current Python 3 installer. We tested on **Python 3.11 or newer**.
3. Run it.
4. Test it.

```bash
python3 --version
```

If that prints a Python 3 version, you are good.

### Ubuntu

```bash
sudo apt update
sudo apt install -y python3-full python3-pip python-is-python3 git unzip
python --version
```

If `python` does not work but `python3` does, use `python3` in the commands below.

### Arch Linux

```bash
sudo pacman -Syu --needed python python-pip git unzip
python --version
```

If `python` does not work but `python3` does, use `python3` in the commands below.

---

## Step 3: Create the virtual environment and install packages

This creates a private Python sandbox just for WyrmGPT.

What this step does:

- creates and activates the virtual environment
- installs everything from `requirements.txt`

That file currently installs these major pieces:

- FastAPI
- Uvicorn
- OpenAI SDK
- pypdf
- python-docx
- qdrant-client
- tiktoken
- python-dotenv

### Windows

Run these in PowerShell Terminal from the repo root:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Alternatively you can simply run the following:
# .\Install-Requirements.ps1
```

If PowerShell complains about script execution being blocked, you can run this once in the same PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then run the install script again.

**Pro-tip**: Folders that you extracted from web downloads may be marked as unsafe for execution. You can right-click the folder and go to Properties to unblock execution for these files.

### Mac

Run these in Terminal from the repo root:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

### Ubuntu / Arch Linux

Run these in your terminal from the repo root:

```bash
python -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

If your system wants `python3` instead of `python`, use that.

---

## Step 4: Add your OpenAI API key

This version of WyrmGPT needs your API key for:

- normal chatting
- title generation
- summaries
- embeddings

Create a new file in the repo root named:

```text
config.secrets.toml
```

**Pro-tip**: The easiest way to do this is make a copy of the provided `config.secrets.toml.example` as a starting point.

Put this in it:

```toml
[providers.openai]
api_key = "YOUR_OPENAI_API_KEY_HERE"
model = "gpt-5.4"
summary_model = "gpt-5-mini"
```

Replace `YOUR_OPENAI_API_KEY_HERE` with your real key.

That is enough for first-time setup.

You do **not** need to edit `config.toml` just to get started.

---

## Step 5: Start the app once

This first run confirms the app boots.

### Windows

Simplest path:

```powershell
.\Start-Service.ps1
```

If PowerShell blocks scripts, use the above bypass, or try this instead:

```powershell
.\.venv\Scripts\activate.bat
.\.venv\Scripts\python.exe -m uvicorn server.main:app --reload --port 8000
```

### Mac

```bash
./.venv/bin/python -m uvicorn server.main:app --reload --port 8000
```

### Ubuntu / Arch Linux

```bash
./.venv/bin/python -m uvicorn server.main:app --reload --port 8000
```

Then open this in your browser:

```text
http://127.0.0.1:8000
```

If the page loads, the basic install works.

In the terminal window (not the browser), stop the server with `Ctrl+C`.

---

## Step 6: Export your ChatGPT data from OpenAI

You need your exported history before WyrmGPT can import it.

In ChatGPT, request a data export. As of March 14, 2026, the official OpenAI help flow is:

1. Open **Settings**.
2. Go to **Data Controls**.
3. Choose **Export Data**.
4. Wait for the email. Depending how much data you have, it could take a few days.
5. Download the export ZIP from the email link.

After you download it, either:

- keep it as a `.zip`, or
- extract it to a folder

The importer supports either one.

**Pro-tip**: You can extract the ZIP to a folder and use the move commands in the import script to save storage space and duplicated files. (Use `--move-root-files` in the args of the import script below.)

---

## Step 7: Import your exported OpenAI data into WyrmGPT

Use the path to your export ZIP or extracted export folder.

**Pro-tip**: If you have a lot of data, it is best to try the commands below first with the optional `--limit 10` argument added. That imports only 10 conversations so you can catch obvious nonsense before you throw the whole archive at it.

If that looks good, then do the real import:

### Windows example

**Important**: If you've just launched a new PowerShell instance, you need to activate the virtual environment again. From the project root:

```powershell
# Optionally:
#.\.venv\Scripts\activate.bat
.\.venv\Scripts\python.exe .\server\scripts\import_openai.py "C:\Users\YourName\Downloads\chatgpt-export.zip" --skip-existing --reindex
```

### Mac example

```bash
./.venv/bin/python ./server/scripts/import_openai.py ~/Downloads/chatgpt-export.zip --skip-existing --reindex
```

### Ubuntu / Arch Linux example

```bash
./.venv/bin/python ./server/scripts/import_openai.py ~/Downloads/chatgpt-export.zip --skip-existing --reindex
```

What this does:

- creates local conversations from your exported ChatGPT history
- imports related metadata
- refreshes transcript artifacts as needed
- reindexes imported text into the local retrieval corpus

If your export is already extracted, point the script at the folder instead of the ZIP.

Example:

```bash
./.venv/bin/python ./server/scripts/import_openai.py ~/Downloads/chatgpt-export --skip-existing --reindex
```

### What those flags mean

- `--refresh-transcripts` = rebuild transcript artifacts for imported conversations
- `--reindex` = build/update the searchable text index after import
- `--ingest-root-files` = import matching root-level export assets (files) when present
- `--move-root-files` = move the files instead of copying them (only works with extracted folders; ZIPs still copy files instead of moving)

### Other important notes

- In Windows, if your export path has spaces, keep the whole path in quotes.
- The importer creates a log file under: `data/import_logs/`
- Imported conversation IDs are prefixed with `oaiexport-` by default.
- The importer can also preserve metadata from the export, not just plain transcript text.

---

## Step 8: Build embeddings

This is the step that gives you embedding-based retrieval over the imported corpus.

What it does:

- Finds corpus chunks in the index that do not yet have embeddings
- Calls the OpenAI embeddings API
- Stores vectors in the local Qdrant-backed vector store under `data/qdrant/`
- Updates embedding state in the local database

This is the step that turns your imported history into something semantic retrieval can use.

In normal human terms: this is what helps WyrmGPT find things by meaning, not just by exact keyword.

Full-text search works without embeddings. It just doesn't work as well.

**Warning**: This operation can take a long time to complete. Brace yourself.

### Windows

```powershell
.\.venv\Scripts\python.exe .\server\scripts\rebuild_embeddings.py
```

### Mac

```bash
./.venv/bin/python ./server/scripts/rebuild_embeddings.py
```

### Ubuntu / Arch Linux

```bash
./.venv/bin/python ./server/scripts/rebuild_embeddings.py
```

Let it finish.

Depending on how much history you imported, this may take a while and will consume OpenAI embedding API calls.

---

## Step 9: Start the app again and use it

Start the server the same way you did in Step 5.

Then open:

```text
http://127.0.0.1:8000
```

At this point you should have:

- a working WyrmGPT install
- your imported ChatGPT history in the local database
- transcript and corpus records built from that import
- embeddings created for retrievable chunks

---

## Troubleshooting

### “python is not recognized”

Python is either not installed or not on your PATH.

Fix: reinstall Python and make sure **Add Python to PATH** is checked. Maybe restart your PC.

### PowerShell refuses to run `.ps1` scripts

Run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then try again.

### “Could not find venv Python” when starting the service

You skipped the virtual environment step or the install step failed.

Fix:

```powershell
python -m venv .venv
.\Install-Requirements.ps1
```

### The import command fails on a path with spaces

Put the path in quotes.

Correct:

```powershell
.\.venv\Scripts\python.exe server\scripts\import_openai.py "C:\Users\YourName\My Files\chatgpt export.zip"
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

## Where your data lives

WyrmGPT stores its local working data in the repo’s `data` folder.

The important locations are:

```text
data\sql\wyrmgpt.sqlite3
```

This is the main SQLite database.

```text
data\qdrant\
```

This is the local vector store used for embeddings.

```text
data\embedding_cache\
```

This is the embedding cache.

```text
data\import_logs\
```

This stores importer log files.

If you care about your work, back up the `data` folder.

---

## The shortest possible version

If you already know what you are doing, this is the bare minimum.

### Windows

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create `config.secrets.toml`:

```toml
[providers.openai]
api_key = "YOUR_OPENAI_API_KEY_HERE"
model = "gpt-5.4"
summary_model = "gpt-5-mini"
```

Then:

```powershell
.\.venv\Scripts\python.exe .\server\scripts\import_openai.py "C:\path\to\chatgpt-export.zip" --skip-existing --reindex
.\.venv\Scripts\python.exe .\server\scripts\rebuild_embeddings.py
.\Start-Service.ps1
```

### Mac

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

Create `config.secrets.toml`:

```toml
[providers.openai]
api_key = "YOUR_OPENAI_API_KEY_HERE"
model = "gpt-5.4"
summary_model = "gpt-5-mini"
```

Then:

```bash
./.venv/bin/python ./server/scripts/import_openai.py ~/Downloads/chatgpt-export.zip --skip-existing --reindex
./.venv/bin/python ./server/scripts/rebuild_embeddings.py
./.venv/bin/python -m uvicorn server.main:app --reload --port 8000
```

### Ubuntu / Arch Linux

```bash
python -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

Create `config.secrets.toml`:

```toml
[providers.openai]
api_key = "YOUR_OPENAI_API_KEY_HERE"
model = "gpt-5.4"
summary_model = "gpt-5-mini"
```

Then:

```bash
./.venv/bin/python ./server/scripts/import_openai.py ~/Downloads/chatgpt-export.zip --skip-existing --reindex
./.venv/bin/python ./server/scripts/rebuild_embeddings.py
./.venv/bin/python -m uvicorn server.main:app --reload --port 8000
```

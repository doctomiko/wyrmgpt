# WyrmGPT First-Time Setup Guide

This guide is for someone who has **never installed WyrmGPT before** and wants to go from:

**“I downloaded the repo”**

to:

**“My exported ChatGPT/OpenAI history is imported and embeddings have been built.”**

This is written for a normal Windows user, not a Python goblin.

---

## What you are doing, in plain English

You are setting up a local web app on your own PC.

That app will:

- store your chats and files in a local SQLite database
- let you use OpenAI models through your own API key
- import your exported ChatGPT history from OpenAI
- build embeddings so WyrmGPT can search your past history more intelligently

---

## Before you start

You need these things:

1. A Windows PC.
2. An internet connection. (Duh!)
3. An OpenAI API key. See https://platform.openai.com/api-keys
4. Your exported ChatGPT data as a `.zip` file, or an extracted export folder.
5. About 10–20 minutes of setup time, plus however long your import and embedding build takes.

---

## Step 1: Install Python

If you do not already have Python installed:

1. Go to the official Python website. https://www.python.org/
2. Download **Python 3.11 or newer**.
3. Run the installer.
4. **Important:** check the box that says **Add Python to PATH** before you click Install.
5. Finish the install.
6. You may need to restart Windows to update the PATH.

After that, open **PowerShell** and test it:

```powershell
python --version
```

**Important**: Note that some installations will prefer "py" instead of "python".

**Pro-tip**: You can right-click any folder and choose Run in Terminal to load Powershell at that location.

If that prints a version number, you're good.

If it says Python is not found, close PowerShell, open a fresh one, and try again.

---

## Step 2: Download the WyrmGPT repo

You can do this either with Git or by downloading a ZIP.

For a beginner, the ZIP route is easier:

1. Download the WyrmGPT repository ZIP. https://github.com/doctomiko/wyrmgpt
2. Extract it somewhere sensible, like:

```text
C:\Users\YourName\Documents\WyrmGPT
```

Do **not** leave it buried inside `Downloads` forever. Put it somewhere you can find again.

**Pro-tip**: You can and should make a folder like X:\Repo or X:\RunPortable to store projects that pull source code from Git and/or do not have MSI Installer dependencies.

---

## Step 3: Open PowerShell in the WyrmGPT folder

Go into the folder you extracted.

Then either:

- right-click in the folder and choose **Open in Terminal**, or
- open PowerShell and `cd` into that folder

Example:

```powershell
cd "C:\Users\YourName\Documents\WyrmGPT"
```

You should be standing in the folder that contains files like:

- `README.md`
- `requirements.txt`
- `Install-Requirements.ps1`
- `Start-Service.ps1`
- `config.toml`
- `server\`

---

## Step 4: Create the Python virtual environment

This creates a private Python sandbox just for WyrmGPT.

Run:

```powershell
python -m venv .venv
```

That will create a `.venv` folder.

---

## Step 5: Install WyrmGPT’s Python packages

The repo already includes a helper script for this.

Run:

```powershell
.\Install-Requirements.ps1
```

What it does:

- activates the virtual environment
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

If PowerShell complains about script execution being blocked, run this once in the same PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then run the install script again.

**Pro-tip**: Folders that you extracted from web downloads may be marked as unsafe for execution. You can right-click the folder and go to Properties to unblock the files.

---

## Step 6: Add your OpenAI API key

WyrmGPT needs your API key for:

- normal chatting
- title generation
- summaries
- embeddings

The cleanest way in this repo is to create a file named:

```text
config.secrets.toml
```

Put it in the **root of the repo**.

Create that file with this content:

```toml
[providers.openai]
api_key = "YOUR_OPENAI_API_KEY_HERE"
```

Replace `YOUR_OPENAI_API_KEY_HERE` with your real key.

You do **not** need to edit Python files.

You usually also do **not** need to edit `config.toml` just to get started.

**Pro-tip**: Copy the provided example.toml file to have a good starting point from scratch.

### Optional: choose your default chat models

If you want, you can add this too:

```toml
[providers.openai]
api_key = "YOUR_OPENAI_API_KEY_HERE"
model = "gpt-5.4"
summary_model = "gpt-5-mini"
```

If you do nothing, the repo already has defaults in `config.toml`.

---

## Step 7: Start WyrmGPT once

Start the local web server:

```powershell
.\Start-Service.ps1
```

If it starts cleanly, you should see it launching Uvicorn on port 8000.

Then open a browser and go to:

```text
http://127.0.0.1:8000
```

If the page loads, congratulations, the basic app is alive.

You can stop the server later with:

```text
Ctrl+C
```

---

## Step 8: Export your ChatGPT data from OpenAI

You need your exported history before WyrmGPT can import it.

In ChatGPT, request a data export. As of March 13, 2026, the official OpenAI help flow is:

1. Sign in to ChatGPT.
2. Click your profile icon.
3. Open **Settings**.
4. Open **Data Controls**.
5. Choose **Export Data**.
6. Confirm the export.

OpenAI says the download link is sent by email and the link expires after 24 hours.

Download that ZIP file somewhere you can find it.

Example:

```text
C:\Users\YourName\Downloads\chatgpt-export.zip
```

You can leave it as a ZIP file. The importer supports either:

- the ZIP itself, or
- an already-extracted export folder

**Pro-tip**: You can extract the ZIP to a folder and use the move commands in the import script to save storage space and duplicated files. (Use "--move-root-files" in the args of the import script below.)

---

## Step 9: Import your exported OpenAI data into WyrmGPT

**Important**: If you've just launched a new PowerShell instance, you need to activate the virtual environment again. From the project root:

```powershell
.\.venv\Scripts\Activate.ps1
```

Back in PowerShell, from the WyrmGPT repo folder, run a **small test first**.

Example:

```powershell
.\.venv\Scripts\python.exe server\scripts\import_openai.py "C:\Users\YourName\Downloads\chatgpt-export.zip" --limit 10
```

That imports only 10 conversations so you can catch obvious nonsense before you throw the whole archive at it.

If that looks good, do the real import:

```powershell
.\.venv\Scripts\python.exe server\scripts\import_openai.py "C:\Users\YourName\Downloads\chatgpt-export.zip" --refresh-transcripts --reindex --ingest-root-files
```

### What those flags mean

- `--refresh-transcripts` = rebuild transcript artifacts for imported conversations
- `--reindex` = build/update the searchable text index after import
- `--ingest-root-files` = import matching root-level export assets when present
- `--move-root-files` = move the files instead of copying them (only works with extracted folders, not ZIPs)

### Important notes

- If your export path has spaces, keep the whole path in quotes.
- The importer creates a log file under:

```text
data\import_logs\
```

- Imported conversation IDs are prefixed with `oaiexport-` by default.
- The importer can also preserve metadata from the export, not just plain transcript text.

---

## Step 10: Build embeddings

Once the import has finished and reindexing is done, build embeddings.

Run:

```powershell
.\.venv\Scripts\python.exe server\scripts\rebuild_embeddings.py
```

This script:

- finds corpus chunks that do not yet have embeddings
- calls the OpenAI embeddings API
- stores vectors in the local Qdrant-backed vector store under `data\qdrant`
- updates embedding state in the local database

This is the step that turns your imported history into something semantic retrieval can use.

In normal human terms: this is what helps WyrmGPT find things by meaning, not just by exact keyword.

---

## Step 11: Start the app again and use it

If the server is not already running, start it again:

```powershell
.\Start-Service.ps1
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

## The shortest possible command list

If you already understand what you are doing, this is the no-nonsense version:

```powershell
cd "C:\path\to\WyrmGPT"
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\Install-Requirements.ps1
```

Create `config.secrets.toml`:

```toml
[providers.openai]
api_key = "YOUR_OPENAI_API_KEY_HERE"
```

Run the app once:

```powershell
.\Start-Service.ps1
```

Import a small test:

```powershell
.\.venv\Scripts\python.exe server\scripts\import_openai.py "C:\path\to\chatgpt-export.zip" --limit 10
```

Do the real import:

```powershell
.\.venv\Scripts\python.exe server\scripts\import_openai.py "C:\path\to\chatgpt-export.zip" --refresh-transcripts --reindex --ingest-root-files
```

Build embeddings:

```powershell
.\.venv\Scripts\python.exe server\scripts\rebuild_embeddings.py
```

Start the app again:

```powershell
.\Start-Service.ps1
```

Open:

```text
http://127.0.0.1:8000
```

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

## Recommended first-run workflow

If you want the least painful path, do it in this order:

1. Install Python.
2. Download and extract WyrmGPT.
3. Create `.venv`.
4. Run `Install-Requirements.ps1`.
5. Create `config.secrets.toml` with your API key.
6. Start the app once and confirm `http://127.0.0.1:8000` loads.
7. Request and download your ChatGPT export.
8. Run a small import test with `--limit 10`.
9. Run the full import with `--refresh-transcripts --reindex --ingest-root-files`.
10. Run `rebuild_embeddings.py`.
11. Start the app again and use it.

That is the sane path.

Not glamorous, but sane.

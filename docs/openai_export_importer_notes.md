# OpenAI export importer for WyrmGPT

This importer reads the **zip file directly** and preserves more than plain transcript text.

## What it imports

It imports the current branch of each conversation from `conversations.json` into your normal tables:

- `conversations`
- `messages`

Then it preserves OpenAI-specific metadata in dedicated side tables it creates automatically:

- `openai_import_user`
- `openai_import_conversations`
- `openai_import_messages`
- `openai_import_feedback`
- `openai_import_assets`
- `openai_import_attachments`

## Why this shape

Your export contains:

- 537 conversations
- `message_feedback.json`
- `user.json`
- lots of DALL·E assets
- message metadata for model slugs, request IDs, recipients, tool calls, attachments, content references, etc.

Flattening all of that into plain transcript text would throw away the useful bits.

This importer preserves:
- OpenAI conversation IDs
- OpenAI node/message IDs
- model slugs
- recipients (`python`, `web.run`, etc.)
- content type (`text`, `code`, `execution_output`, `thoughts`, etc.)
- request IDs
- raw metadata/content JSON
- attachments and whether binaries are present in the zip
- feedback rows
- user-profile export metadata

## Important current limitation

It imports the **current branch only** using `current_node`.

That avoids duplicating alternate branches on pass one.
The export still contains the full mapping, and the importer stores branch-level metadata like node counts.

## Stripped root `file_*.png` files

That is fine.

The importer does **not** require binaries to exist.
It records attachment metadata and flags whether matching binaries are present in the zip.

## How to use it

Copy the script into:

`server/scripts/import_openai_export_zip.py`

Then test small:

```powershell
python server\scripts\import_openai_export_zip.py "M:\path\to\openai export tomiko.zip" --limit 10
```

Then do the real pass:

```powershell
python server\scripts\import_openai_export_zip.py "M:\path\to\openai export tomiko.zip" --refresh-transcripts --reindex
```

Then build embeddings:

```powershell
python server\scripts\rebuild_embeddings.py
```

## Suggested workflow

1. import conversations/messages + metadata
2. refresh transcripts
3. reindex corpus
4. rebuild embeddings

Do not do all four at once until the first small test looks sane.

# ChatGPT DOM Extension Overview

This connector imports the existing ChatGPT DOM browser extension into the WyrmGPT repo without changing its runtime behavior.

## What it does

- runs locally in the browser on `chatgpt.com`
- reads the currently rendered conversation DOM
- exports chats as JSON, Markdown, or single-file HTML
- supports user-controlled backup behaviors like manual backup, backup-on-load, and auto-backup
- stores settings locally in extension storage

## Repository intent

This folder is organized so each concern is easy to find:

- deployable extension source in `../extension/`
- packaged ZIP artifact in `../release/`
- non-packaged source art in `../assets/source-art/`

That keeps loadable extension files separate from reference assets that are not meant to ship inside the browser payload.

## Provenance

Imported from the inspected extension snapshot previously unpacked under `_inspect/chatgptdom-extension/chatgptdom-extension`.

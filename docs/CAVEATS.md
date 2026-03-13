# CAVEATS.md

---

## Version History

### Version 1

The original short list of caveats that are now described in this document's summary.

### Version 2

This document expands the original short caveats, with more explicit, actionable warnings about safety, privacy, and deployment choices.

### Version 3

Adds a short explaination about performance and scalability decisions and the disposition of any scalable versions that may come later.

---

## Executive Summary

This document explains important things about WyrmGPT in very simple words.

It is a local tool. That means it runs on your computer.
But it is not locked or hidden.
If someone can open your computer, they can read your chats.
There is no lock or password in the app.

Your words are sent to OpenAI to get answers.
So the text is not only on your computer.
If you share private or secret things, they may leave your computer.

Pinned memories are treated as true by the assistant.
If a pinned memory is wrong, the assistant may keep using the wrong idea. This can make mistakes last longer.

The app can show two answers (A/B). You choose one to keep. The one you choose becomes the “official” one for later. If you choose a bad answer, the app will keep using it. You can reverse this at any time.

The app can make summaries of your chats. Summaries are shorter and can miss details. Sometimes they can be wrong. The app uses the summary later, so a wrong summary can cause more mistakes.

The assistant’s default voice can be playful or flirty. That is okay for most adults. It would be a bad fit for kids or shared computers. Adjust the system prompt accordingly.

One very good thing: the app shows the “context pack.” That means you can see what text will be sent to the model. This helps you know what the assistant is using.

In short, this app gives you maximum control. But it also makes you responsible for safety and privacy.

---

## Additional caveats & recommendations (v2)

- System prompt and persona: the repository contains `system_prompt.txt` which intentionally sets a chat persona and allows adult or flirtatious replies. Before sharing, deploying, or letting others use the app, audit and (if needed) replace that prompt. Consider removing any language that assumes the user is 18+ if you might expose the app to mixed-age environments.

- Debug exposure: the server defaults to `DEBUG_ERRORS=1` (see `server/main.py`) and exposes debug endpoints such as `/api/debug/routes` and `/api/debug/db`. These can leak stack traces, file paths, and DB locations. Set `DEBUG_ERRORS=0` and remove or protect debug endpoints before any non-development deployment.

- No authentication: there is no authentication layer by default. If you bind the server to anything other than `localhost`, or place it on a LAN, an attacker could read chats or use your OpenAI API key. Add auth (or run behind an authenticated reverse-proxy) and/or firewall/bind to `127.0.0.1`.

- OpenAI key & cost implications: the server uses `OPENAI_API_KEY` server-side and does not encrypt stored content. A/B mode (`POST /api/chat_ab`) calls two models sequentially, so each A/B send doubles API calls and costs. Document this, and treat the API key as sensitive—do not commit it or share it.

- Pinned memories are global: pinned memories are pulled from a single `memory_pins` table and appended to *every* conversation's system prompt (see `server/context.py`). If you expect pins to be per-project or per-conversation, update the code or be careful when pinning sensitive or broad statements.

- Client debug logging: the UI includes `DEBUG_BOOT = true` and verbose console logging in `server/static/app.js`. Turn this off for production to avoid leaking model IDs, conversation IDs, or partial context in browser consoles.

- Model catalog & scripts: `server/scripts/sync_model_catalog.py` requires an OpenAI API key and will write to `server/model_catalog.json`. Back up the catalog before running the script; review its output and expectations.

- Backups & WAL files: the DB lives at `data/sql/wyrmgpt.sqlite3` and the app uses WAL journaling. When backing up the DB, copy the entire `data/` folder and include `-wal` and `-shm` files for a consistent snapshot.

- Migration / reset scripts: `server/scripts/migrate_reset_v2.py` and other helpers may assume an empty DB or perform destructive changes if run recklessly. Warn users in docs before running migration or reset scripts.

- No rate-limiting or abuse controls: the server does not implement request throttling. If you expose the server to multiple users or an untrusted network, consider adding rate-limiting or an authenticated gateway.

- Provider assumptions: the code expects OpenAI-style SDK objects and filters models by prefixes (`gpt-`, `o1`, `o3`, `o4`). If you plan to use alternate LLM providers, validate compatibility.

---

## Database performance considerations

WyrmGPT currently assumes a single-user local deployment. Some storage and indexing choices (e.g., caching extracted file text into the local data directory and maintaining a rebuildable retrieval index) prioritize simplicity and developer ergonomics over multi-tenant scalability. These defaults may change in a future multi-user mode and will likely become configurable, including retention policies and externalized storage options.

Further, developer is making no guarantees that any future multi-user, multi-tenant or scalable deployment modes will continue to be source-available. The reasoning here is the tendency for knock-off ChatGPT clones to take unfair advantage of this source code scaffolding in order to create rip-offs/scammy SaaS services with usory pricing, or indeed for any commercial operations (even legitimate ones) to monetize this codebase without fairly licensing from its authors.

---

## Suggested "Deployment checklist" (short)

1. Audit `system_prompt.txt` and replace if necessary.
2. Bind server to `127.0.0.1` or put behind an authenticated reverse-proxy.
3. Ensure `OPENAI_API_KEY` is stored securely and not committed to any Git repo.
4. Set `DEBUG_ERRORS=0` in your environment for production.
5. Turn off client `DEBUG_BOOT` (set to `false`) in `server/static/app.js`.
6. Back up `data/` (include `-wal`/`-shm`) before running migrations.
7. Note to users: A/B mode doubles model calls and costs.
8. Decide whether pinned memories should remain global; change code if not.
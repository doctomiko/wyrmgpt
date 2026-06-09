# ChatGPT DOM Extension
Written by 'Doc' Tomiko Carpe 2026
Learn more at https://doctorwyrm.com

## A Quick Summary of What This Extension Does
Right now, this extension crawls the visible page content in ChatGPT and captures a data-structure of whatever chat is on the web-page currently loaded. It understands how React works and deals with that, including partially loading or streaming Assistant responses.

It can also theoretically be used to place text into the input field textbox and simulate pressing Send when explicitly instructed, but so far nothing calls that yet.

The extension has hotkeys to let you export the current chat thread. You can do JSON, Markdown, or HTML. Or you can use the backup features (auto, on-load, and manual) to seamlessly make local copies of your chats in all the formats that you desire.

## Default hotkeys
- `Ctrl+Shift+K` - keyboard overlay
- `Ctrl+Shift+S` - save JSON
- `Ctrl+Shift+M` - save Markdown
- `Ctrl+Shift+H` - save single-file HTML
- `Ctrl+Shift+A` - toggle auto-backup
- `Ctrl+Shift+L` - toggle backup-on-load
- `Ctrl+Shift+B` - backup now

## Behavior summary
The extension is intended as a local, user-controlled tool. It runs only on `https://chatgpt.com/*`, works from rendered page content, stores config locally, and does not send chat data to remote services in this version.

## Status
Active development. APIs, hotkeys, and configuration may change.

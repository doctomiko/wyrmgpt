# Web UI Connector

This connector houses the browser extension that bridges an active `chatgpt.com` page into a local, user-controlled export/integration surface.

## Layout

- `extension/` - unpacked browser extension source for "Load unpacked" installs
- `release/` - preserved packaged artifact (`chatgpt-dom-extension.zip`)
- `assets/source-art/` - non-packaged art assets kept separate from the loadable extension payload
- `docs/` - connector-specific documentation

## Notes

- The extension currently targets `https://chatgpt.com/*`.
- The files under `extension/` are the ones a Chromium/Edge developer install should point at.
- The ZIP is preserved for archival/release convenience, but browsers still need the unpacked folder for local developer installs.

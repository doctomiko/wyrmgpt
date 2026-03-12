# WyrmGPT TOML refactor clean pass

## Part 1 — backup and replace `server/config.py`

Back up first:

```powershell
Copy-Item server\config.py server\config.py.bak.20260312
```

Then replace `server/config.py` with the attached full drop-in.

## Part 2 — add TOML files

Add these at repo root:

- `config.toml`
- `config.secrets.toml`

`config.toml` is the normal config.
`config.secrets.toml` is for API keys and other secrets.

The loader merges them in this order:

1. `config.toml`
2. `config.secrets.toml`
3. `.env` fallback only when TOML is missing a value

Optional overrides:
- `WYRMGPT_CONFIG_TOML`
- `WYRMGPT_SECRETS_TOML`

## Part 3 — replace direct env usage with `*Config` objects

### `server/main.py`

1. Delete:
```python
import os
from dotenv import load_dotenv
```

2. Delete:
```python
DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "1") == "1"
load_dotenv()
```

3. Replace with:
```python
core_cfg = load_core_config()
oai_cfg = load_openai_config()
DEBUG_ERRORS = core_cfg.debug_errors
client = OpenAI(api_key=oai_cfg.open_ai_apikey)
MODEL = oai_cfg.open_ai_model
TITLE_MODEL = oai_cfg.summary_model
```

4. Remove the later duplicate:
```python
oai_cfg = load_openai_config()
MODEL = oai_cfg.open_ai_model
TITLE_MODEL = oai_cfg.summary_model
```

### `server/scripts/summarize_conversations.py`

Replace:
```python
ap.add_argument("--model", default=os.getenv("SUMMARY_MODEL") or os.getenv("MODEL") or ctx_cfg.estimate_model or "gpt-5-mini")
```

with:
```python
ap.add_argument("--model", default=oai_cfg.summary_model or ctx_cfg.estimate_model or "gpt-5-mini")
```

### `server/scripts/sync_model_catalog.py`

Replace the file with:

```python
from pathlib import Path
import json
import os
import sys
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.config import load_openai_config

ALLOWED_PREFIXES = ("gpt-", "o1", "o3", "o4")

oai_cfg = load_openai_config()
client = OpenAI(api_key=oai_cfg.open_ai_apikey)

catalog_path = ROOT / "server" / "model_catalog.json"

if catalog_path.exists():
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
else:
    catalog = {}

models = []
for m in client.models.list():
    mid = m.id
    if mid.startswith(ALLOWED_PREFIXES):
        models.append(mid)

for mid in models:
    if mid not in catalog:
        catalog[mid] = {
            "vendor": "OpenAI",
            "display_name": mid,
            "description": "Auto-generated stub entry; fill in details if you actually use this.",
            "input_cost_per_million": None,
            "output_cost_per_million": None,
            "context_window": None,
            "tags": ["auto-stub"]
        }

catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
print(f"Synced {len(models)} models; catalog now has {len(catalog)} entries.")
```

## Test sequence

1. Leave `.env` in place.
2. Add `config.toml` and `config.secrets.toml`.
3. Start app.
4. Verify UI config reflects TOML values.
5. Verify OpenAI calls still work.
6. Verify summarization script still works.
7. Verify sync model catalog still works.

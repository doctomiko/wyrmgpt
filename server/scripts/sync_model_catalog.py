from pathlib import Path
import json
from openai import OpenAI

ALLOWED_PREFIXES = ("gpt-", "o1", "o3", "o4")

client = OpenAI()

ROOT = Path(__file__).resolve().parents[1]
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
from pathlib import Path
from fastapi import FastAPI
from contextlib import asynccontextmanager

from server.providers.registry import ProviderRegistry
from server.providers.types import ModelCatalog
from .config import load_core_config, load_tool_config
from .db import (
    init_schema, db_debug_info, DATA_DIR,
)
from .tools.registry import ToolRegistry, load_tool_registry

CORE_CFG = load_core_config()
TOOL_CFG = load_tool_config()
DEBUG_ERRORS = CORE_CFG.debug_errors

MODEL_CATALOG: ModelCatalog = {}
PROVIDER_REGISTRY: ProviderRegistry | None = None
TOOL_REGISTRY: ToolRegistry | None = None


# Replaces the old @app.on_event("startup") and @app.on_event("shutdown") handlers with a single async context manager that can do both setup and teardown.
#@app.on_event("startup")
#def _startup():
#    init_db()
@asynccontextmanager
async def init_runtime(app: FastAPI):
    # --- STARTUP ---
    from server.routes.deployments import build_provider_registry, load_model_catalog

    global MODEL_CATALOG, PROVIDER_REGISTRY, TOOL_REGISTRY
    print("[DB]", db_debug_info())
    init_schema()
    MODEL_CATALOG = load_model_catalog()
    PROVIDER_REGISTRY = build_provider_registry(MODEL_CATALOG)
    TOOL_REGISTRY = load_tool_registry(TOOL_CFG)

    # If you need anything else (loading model lists, warm caches…)
    # you put it here.

    yield  # <-- the app runs after this line

    # --- SHUTDOWN ---
    # Cleanup if you ever need it


# -------------------------
# Global Vars
# -------------------------

# start from root folder above ./server
HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
# This is where uploaded files are stored; you can change this or add subdirs as needed
SOURCES_ROOT = DATA_DIR / "sources"
# This is where APIs for supported toools (retrievers, file parsers, etc.) would live; you can add subdirs as needed
TOOLS_DIR = HERE / "tools"

MODEL_CATALOG_PATH = HERE / "model_catalog.json"
TOOL_CATALOG_PATH = HERE / "tool_catalog.json"

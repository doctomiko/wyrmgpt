# -------------------------
# Base API Endpoints
# -------------------------
# This file holds all the core endpoints for the API.
# That includes some configuration readers / setters.
# It is also where you get the app object from.

import traceback
from typing import Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.api_models import AppConfigUpdateRequest, ModelSettingsUpdateRequest, QuerySettingsUpdateRequest
from server.config import APP_KEYS, QUERY_EXPAND_ALLOWED, QUERY_INCLUDE_ALLOWED, _normalize_csv_set, load_app_config, load_retrieval_config, load_ui_config
from server.db import delete_app_settings_by_prefix, get_app_setting, invalidate_all_context_cache, set_app_setting
from server.db_helpers import db_debug_info
from server.runtime import DEBUG_ERRORS, STATIC_DIR, init_runtime

app = FastAPI(lifespan=init_runtime)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# region Base API stuffs

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    print(f"\n[ERROR] {request.method} {request.url.path} -> {type(exc).__name__}: {exc}")
    print(tb)

    payload: dict[str, Any] = {
        "detail": "Internal Server Error",
        "path": request.url.path,
    }
    if DEBUG_ERRORS:
        payload["error"] = f"{type(exc).__name__}: {exc}"
        # Keep it readable; last 30 lines is usually enough
        payload["traceback_tail"] = tb.splitlines()[-30:]

    return JSONResponse(payload, status_code=500)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/debug/routes")
def api_debug_routes():
    return [getattr(r, "path", None) for r in app.router.routes]

@app.get("/api/debug/db")
def api_debug_db():
    return JSONResponse(db_debug_info())

@app.get("/api/health")
def health():
    from server.routes.deployments import get_default_chat_target

    target = get_default_chat_target()
    return JSONResponse(
        {
            "ok": True,
            "default_chat_deployment": target.id,
            "provider": target.provider_id,
            "model": target.model,
        }
    )

#endregion

# region Query Config Helpers

def _query_setting_key(key: str) -> str:
    return f"query.{key}"

def _get_effective_query_setting(project_id: int | None, key: str, env_default: str) -> str:
    if project_id is not None:
        v = get_app_setting(_query_setting_key(key), None, "project", str(project_id))
        if v is not None and str(v).strip() != "":
            return str(v)
    v = get_app_setting(_query_setting_key(key), None, "global", "")
    if v is not None and str(v).strip() != "":
        return str(v)
    return env_default


def _model_setting_key(key: str) -> str:
    return f"model.{key}"


_MODEL_SETTINGS_DEFAULTS: dict[str, Any] = {
    "temperature": 0.7,
    "thinking_level": 0,
    "show_thinking": True,
    "verbosity": 5,
    "tool_aggressiveness": 5,
    "max_output_tokens": None,
    "top_p": None,
    "top_k": None,
}


_MODEL_SETTING_TYPES: dict[str, str] = {
    "temperature": "float",
    "thinking_level": "int",
    "show_thinking": "bool",
    "verbosity": "int",
    "tool_aggressiveness": "int",
    "max_output_tokens": "int",
    "top_p": "float",
    "top_k": "int",
}


def _parse_model_setting_value(key: str, raw: str | None) -> Any:
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "":
        return None
    kind = _MODEL_SETTING_TYPES.get(key, "string")
    try:
        if kind == "bool":
            return s.lower() in {"1", "true", "yes", "on"}
        if kind == "int":
            return int(s)
        if kind == "float":
            return float(s)
    except Exception:
        return None
    return s


def _serialize_model_setting_value(key: str, value: Any) -> str:
    kind = _MODEL_SETTING_TYPES.get(key, "string")
    if kind == "bool":
        return "1" if bool(value) else "0"
    return str(value)


def _coerce_model_setting_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key == "temperature":
        return max(0.0, min(2.0, float(value)))
    if key == "thinking_level":
        return max(0, min(10, int(value)))
    if key in {"verbosity", "tool_aggressiveness"}:
        return max(0, min(10, int(value)))
    if key == "max_output_tokens":
        return max(1, int(value))
    if key == "top_p":
        return max(0.0, min(1.0, float(value)))
    if key == "top_k":
        return max(1, int(value))
    if key == "show_thinking":
        return bool(value)
    return value


def _normalize_scope(scope_type: str, scope_id: str) -> tuple[str, str]:
    st = (scope_type or "global").strip().lower()
    sid = (scope_id or "").strip()
    if st not in {"global", "project", "conversation"}:
        st, sid = "global", ""
    if st == "global":
        sid = ""
    return st, sid


def _scope_chain_for_model_settings(scope_type: str, scope_id: str) -> list[tuple[str, str]]:
    from server.db import db_get_conversation_project_id
    from server.db_helpers import db_session
    st, sid = _normalize_scope(scope_type, scope_id)
    if st == "global":
        return [("global", "")]
    if st == "project":
        return [("project", sid), ("global", "")]
    project_id = None
    if sid:
        try:
            with db_session() as conn:
                project_id = db_get_conversation_project_id(conn, sid)
        except Exception:
            project_id = None
    chain = [("conversation", sid)]
    if project_id is not None:
        chain.append(("project", str(project_id)))
    chain.append(("global", ""))
    return chain


def get_effective_model_settings(scope_type: str = "global", scope_id: str = "") -> dict[str, Any]:
    effective = dict(_MODEL_SETTINGS_DEFAULTS)
    for key in _MODEL_SETTINGS_DEFAULTS:
        for st, sid in _scope_chain_for_model_settings(scope_type, scope_id):
            parsed = _parse_model_setting_value(key, get_app_setting(_model_setting_key(key), None, st, sid))
            if parsed is not None:
                effective[key] = parsed
                break
    return effective


def _get_local_model_settings(scope_type: str = "global", scope_id: str = "") -> dict[str, Any]:
    st, sid = _normalize_scope(scope_type, scope_id)
    return {key: _parse_model_setting_value(key, get_app_setting(_model_setting_key(key), None, st, sid)) for key in _MODEL_SETTINGS_DEFAULTS}

#endregion

# region App Config Endpoints

@app.get("/api/ui_config")
def api_ui_config():
    cfg = load_ui_config()
    return JSONResponse(
        {
            "local_timezone": cfg.local_timezone,
            "context_preview_limit_min": cfg.context_preview_limit_min,
            "context_preview_limit_max": cfg.context_preview_limit_max,
            "min_rag_query_text_len": cfg.min_rag_query_text_len,
            "context_idle_ms": cfg.context_idle_ms,
            "transcript_idle_ms": cfg.transcript_idle_ms,
            "debug_boot": cfg.debug_boot,
        }
    )


@app.get("/api/app_config")
def api_app_config():
    cfg = load_app_config()
    return JSONResponse(
        {
            "search_chat_history": cfg.search_chat_history,
        }
    )


@app.post("/api/app_config")
def api_update_app_config(req: AppConfigUpdateRequest):
    if req.search_chat_history is not None:
        set_app_setting(
            APP_KEYS.search_chat_history,
            "1" if req.search_chat_history else "0",
        )

    cfg = load_app_config()
    return JSONResponse(
        {
            "ok": True,
            "search_chat_history": cfg.search_chat_history,
        }
    )


@app.get("/api/query_settings")
def api_get_query_settings(scope_type: str = "global", scope_id: str = ""):
    from server.db import get_app_setting

    qcfg = load_retrieval_config()

    scope_type = (scope_type or "global").strip().lower()
    scope_id = (scope_id or "").strip()

    if scope_type == "project" and scope_id:
        project_id = int(scope_id)
    else:
        project_id = None
        scope_type = "global"
        scope_id = ""

    effective_query_include = _get_effective_query_setting(project_id, "include", qcfg.query_include)
    effective_query_expand = _get_effective_query_setting(project_id, "expand_results", qcfg.query_expand_results)
    effective_max_files = _get_effective_query_setting(project_id, "max_full_files", str(qcfg.query_max_full_files))
    effective_max_memories = _get_effective_query_setting(project_id, "max_full_memories", str(qcfg.query_max_full_memories))
    effective_max_chats = _get_effective_query_setting(project_id, "max_full_chats", str(qcfg.query_max_full_chats))

    local_query_include = get_app_setting(_query_setting_key("include"), None, scope_type, scope_id)
    local_query_expand = get_app_setting(_query_setting_key("expand_results"), None, scope_type, scope_id)
    local_max_files = get_app_setting(_query_setting_key("max_full_files"), None, scope_type, scope_id)
    local_max_memories = get_app_setting(_query_setting_key("max_full_memories"), None, scope_type, scope_id)
    local_max_chats = get_app_setting(_query_setting_key("max_full_chats"), None, scope_type, scope_id)

    effective_expand_min_hits = _get_effective_query_setting(
        project_id,
        "expand_min_artifact_hits",
        str(qcfg.query_expand_min_artifact_hits),
    )
    effective_chat_window_before = _get_effective_query_setting(
        project_id,
        "expand_chat_window_before",
        str(qcfg.query_expand_chat_window_before),
    )
    effective_chat_window_after = _get_effective_query_setting(
        project_id,
        "expand_chat_window_after",
        str(qcfg.query_expand_chat_window_after),
    )    

    local_expand_min_hits = get_app_setting(
        _query_setting_key("expand_min_artifact_hits"),
        None,
        scope_type,
        scope_id,
    )
    local_chat_window_before = get_app_setting(
        _query_setting_key("expand_chat_window_before"),
        None,
        scope_type,
        scope_id,
    )
    local_chat_window_after = get_app_setting(
        _query_setting_key("expand_chat_window_after"),
        None,
        scope_type,
        scope_id,
    )
    return JSONResponse({
        "scope_type": scope_type,
        "scope_id": scope_id,
        "query_include": local_query_include,
        "query_expand_results": local_query_expand,
        "query_max_full_files": int(local_max_files) if local_max_files not in (None, "") else None,
        "query_max_full_memories": int(local_max_memories) if local_max_memories not in (None, "") else None,
        "query_max_full_chats": int(local_max_chats) if local_max_chats not in (None, "") else None,
        "query_expand_min_artifact_hits": int(local_expand_min_hits) if local_expand_min_hits not in (None, "") else None,
        "query_expand_chat_window_before": int(local_chat_window_before) if local_chat_window_before not in (None, "") else None,
        "query_expand_chat_window_after": int(local_chat_window_after) if local_chat_window_after not in (None, "") else None,

        "effective_query_include": _normalize_csv_set(effective_query_include, QUERY_INCLUDE_ALLOWED),
        "effective_query_expand_results": _normalize_csv_set(effective_query_expand, QUERY_EXPAND_ALLOWED),
        "effective_query_max_full_files": int(effective_max_files),
        "effective_query_max_full_memories": int(effective_max_memories),
        "effective_query_max_full_chats": int(effective_max_chats),
        "effective_query_expand_min_artifact_hits": int(effective_expand_min_hits),
        "effective_query_expand_chat_window_before": int(effective_chat_window_before),
        "effective_query_expand_chat_window_after": int(effective_chat_window_after),
    })


@app.post("/api/query_settings")
def api_update_query_settings(req: QuerySettingsUpdateRequest):
    scope_type = (req.scope_type or "global").strip().lower()
    scope_id = (req.scope_id or "").strip()

    if scope_type not in ("global", "project"):
        raise HTTPException(status_code=400, detail="scope_type must be global or project")

    if scope_type == "global":
        scope_id = ""

    if req.query_include is not None:
        set_app_setting(
            _query_setting_key("include"),
            _normalize_csv_set(req.query_include, QUERY_INCLUDE_ALLOWED),
            scope_type,
            scope_id,
        )

    if req.query_expand_results is not None:
        set_app_setting(
            _query_setting_key("expand_results"),
            _normalize_csv_set(req.query_expand_results, QUERY_EXPAND_ALLOWED),
            scope_type,
            scope_id,
        )

    if req.query_max_full_files is not None:
        set_app_setting(_query_setting_key("max_full_files"), str(int(req.query_max_full_files)), scope_type, scope_id)

    if req.query_max_full_memories is not None:
        set_app_setting(_query_setting_key("max_full_memories"), str(int(req.query_max_full_memories)), scope_type, scope_id)

    if req.query_max_full_chats is not None:
        set_app_setting(_query_setting_key("max_full_chats"), str(int(req.query_max_full_chats)), scope_type, scope_id)

    if req.query_expand_min_artifact_hits is not None:
        if req.query_expand_min_artifact_hits is not None:
            min_hits = max(1, int(req.query_expand_min_artifact_hits))
        set_app_setting(
            _query_setting_key("expand_min_artifact_hits"),
            str(min_hits),
            scope_type,
            scope_id,
        )

    if req.query_expand_chat_window_before is not None:
        set_app_setting(
            _query_setting_key("expand_chat_window_before"),
            str(max(0, int(req.query_expand_chat_window_before))),
            scope_type,
            scope_id,
        )

    if req.query_expand_chat_window_after is not None:
        set_app_setting(
            _query_setting_key("expand_chat_window_after"),
            str(max(0, int(req.query_expand_chat_window_after))),
            scope_type,
            scope_id,
        )
                
    invalidate_all_context_cache()
    return api_get_query_settings(scope_type=scope_type, scope_id=scope_id)


@app.get("/api/model_settings")
def api_get_model_settings(scope_type: str = "global", scope_id: str = ""):
    st, sid = _normalize_scope(scope_type, scope_id)
    return JSONResponse({
        "scope_type": st,
        "scope_id": sid,
        "local": _get_local_model_settings(st, sid),
        "effective": get_effective_model_settings(st, sid),
        "defaults": dict(_MODEL_SETTINGS_DEFAULTS),
    })


@app.post("/api/model_settings")
def api_update_model_settings(req: ModelSettingsUpdateRequest):
    st, sid = _normalize_scope(req.scope_type, req.scope_id)
    if st == "project" and not sid:
        raise HTTPException(status_code=400, detail="project scope_id is required")
    if st == "conversation" and not sid:
        raise HTTPException(status_code=400, detail="conversation scope_id is required")

    updates = {
        "temperature": req.temperature,
        "thinking_level": req.thinking_level,
        "show_thinking": req.show_thinking,
        "verbosity": req.verbosity,
        "tool_aggressiveness": req.tool_aggressiveness,
        "max_output_tokens": req.max_output_tokens,
        "top_p": req.top_p,
        "top_k": req.top_k,
    }
    for key, value in updates.items():
        if value is None:
            continue
        set_app_setting(_model_setting_key(key), _serialize_model_setting_value(key, _coerce_model_setting_value(key, value)), st, sid)

    invalidate_all_context_cache()
    return api_get_model_settings(scope_type=st, scope_id=sid)


@app.delete("/api/model_settings")
def api_reset_model_settings(scope_type: str = "global", scope_id: str = ""):
    st, sid = _normalize_scope(scope_type, scope_id)
    if st == "global":
        raise HTTPException(status_code=400, detail="Global model settings cannot be reset as a group from this endpoint.")
    delete_app_settings_by_prefix(_model_setting_key(""), st, sid)
    invalidate_all_context_cache()
    return api_get_model_settings(scope_type=st, scope_id=sid)

# endregion
from server.api_models import CorpusSearchRequest
from server.config import RetrievalConfig, load_retrieval_config
from server.logging_helper import log_warn

from server.routes.base import app


# region Search Endpoints

@app.post("/api/corpus/search")
def corpus_search(req: CorpusSearchRequest):
    from server.db import db_ensure_files_artifacted_for_conversation, search_corpus_for_conversation

    cid = (req.conversation_id or "").strip()
    q = (req.query or "").strip()

    # We normally would bother to load here, since function will load QueryConfig
    # but we need it anyway for healing function
    cfg: RetrievalConfig = load_retrieval_config()
    include_global=req.include_global
    if req.include_global:
        include_global=req.include_global
        log_warn("corpus_search is using req.include_global which may override cfg.query_global_artifacts, but only for healing functions.")
    else:
        include_global=cfg.query_global_artifacts
    # Optional: self-heal missing artifacts before searching
    db_ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=5, include_global=include_global)
    rows = search_corpus_for_conversation(
        conversation_id=cid,
        query=q,
        limit=req.limit,
        cfg=cfg,
        #include_global=req.include_global,
    )
    return {"ok": True, "results": rows}

# endregion
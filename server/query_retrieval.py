import time
from collections import OrderedDict
from functools import lru_cache
from typing import Dict, List, Tuple

from .config import (
    RetrievalConfig,
    load_retrieval_config,
    load_app_config,
    load_embedding_config,
    load_vector_config,
)
from .query_slicer import slice_user_query
from .query_shaper import shape_fts_query
from .logging_helper import log_debug
from .db import (
    search_corpus_for_conversation,
    get_vector_search_scope,
    get_corpus_chunks_by_ids,
    _sha256_hex,
)
from .providers.openai_embeddings import OpenAIEmbeddingProvider
from .vector.qdrant_local import QdrantLocalVectorStore

# region Cache Helpers

# Simple TTL LRU cache: key -> (expires_at, payload)
_CACHE: "OrderedDict[tuple, tuple[float, dict]]" = OrderedDict()
#_CACHE: "OrderedDict[Tuple[str,str], Tuple[float, List[dict]]]" = OrderedDict()

def _cache_get(key):
    now = time.time()
    v = _CACHE.get(key)
    if not v:
        return None
    exp, data = v
    if exp < now:
        try:
            del _CACHE[key]
        except Exception:
            pass
        return None
    _CACHE.move_to_end(key)
    return data

def _cache_put(key, data, ttl_sec: float, max_entries: int):
    now = time.time()
    _CACHE[key] = (now + ttl_sec, data)
    _CACHE.move_to_end(key)
    while len(_CACHE) > max_entries:
        _CACHE.popitem(last=False)

# endregion
# region Singletons for Vector DB Stuffs

@lru_cache(maxsize=1)
def _embedding_provider():
    emb_cfg = load_embedding_config()
    if emb_cfg.provider != "openai":
        raise NotImplementedError(f"Embedding provider not implemented yet: {emb_cfg.provider}")
    return OpenAIEmbeddingProvider(emb_cfg=emb_cfg)

@lru_cache(maxsize=1)
def _vector_store():
    vec_cfg = load_vector_config()
    if vec_cfg.backend != "qdrant_local":
        raise NotImplementedError(f"Vector backend not implemented yet: {vec_cfg.backend}")
    return QdrantLocalVectorStore(cfg=vec_cfg)

# endregion

def diversify_results(rows: list[dict], limit: int) -> list[dict]:
    out = []
    per_file = {}
    per_artifact = {}
    seen_keys = set()

    for r in rows:
        file_id = r.get("file_id") or ""
        artifact_id = r.get("artifact_id") or ""
        key = (r.get("filename") or "", r.get("chunk_index"), file_id, artifact_id)

        if key in seen_keys:
            continue
        seen_keys.add(key)

        if file_id:
            if per_file.get(file_id, 0) >= 2:
                continue
        if artifact_id:
            if per_artifact.get(artifact_id, 0) >= 2:
                continue

        out.append(r)
        if file_id:
            per_file[file_id] = per_file.get(file_id, 0) + 1
        if artifact_id:
            per_artifact[artifact_id] = per_artifact.get(artifact_id, 0) + 1

        if len(out) >= limit:
            break

    return out

def _retrieval_rank_key(r: dict) -> tuple:
    importance = int(r.get("memory_importance") or 0)
    pinned_rank = 0 if importance >= 10 else 1
    # Lower tuple sorts first
    return (
        pinned_rank,
        -importance,
        float(r.get("score", 1e9)),
    )

def _retrieve_vector_rows_for_query(
    *,
    conversation_id: str,
    query_text: str,
    limit: int,
    cfg: RetrievalConfig,
) -> list[dict]:
    scope = get_vector_search_scope(conversation_id=conversation_id, cfg=cfg)
    query_vector = _embedding_provider().embed_query(query_text)
    if not query_vector:
        return []

    store = _vector_store()
    vec_cfg = load_vector_config()
    store.ensure_collection(vec_cfg.collection_name, len(query_vector))

    hits = store.search(
        query_vector,
        top_k=limit,
        scope_keys=scope["scope_keys"],
        transcript_ids=scope["transcript_cids"],
    )
    if not hits:
        return []

    rows = get_corpus_chunks_by_ids([int(h.chunk_id) for h in hits])
    by_id = {int(r["chunk_id"]): dict(r) for r in rows}

    out: list[dict] = []
    for h in hits:
        row = by_id.get(int(h.chunk_id))
        if not row:
            continue
        row["score"] = float(h.score)
        row["vector_score"] = float(h.score)
        row["fts_score"] = None
        row["rrf_score"] = None
        row["final_score"] = None
        row["retrieval_channels"] = ["vector"]
        out.append(row)

    out.sort(key=lambda r: float(r.get("vector_score") or 0.0), reverse=True)
    return out

def _rrf_merge(
    *,
    fts_rows: list[dict],
    vector_rows: list[dict],
    limit: int,
    rrf_k: int = 60,
) -> list[dict]:
    merged: dict[int, dict] = {}

    for rank, row in enumerate(sorted(fts_rows, key=_retrieval_rank_key), start=1):
        cid = int(row["chunk_id"])
        cur = merged.setdefault(cid, dict(row))
        cur["rrf_score"] = float(cur.get("rrf_score") or 0.0) + (1.0 / (rrf_k + rank))
        cur["fts_score"] = row.get("score")
        cur.setdefault("retrieval_channels", [])
        if "fts" not in cur["retrieval_channels"]:
            cur["retrieval_channels"].append("fts")

    for rank, row in enumerate(sorted(vector_rows, key=lambda r: float(r.get("vector_score") or 0.0), reverse=True), start=1):
        cid = int(row["chunk_id"])
        cur = merged.setdefault(cid, dict(row))
        cur["rrf_score"] = float(cur.get("rrf_score") or 0.0) + (1.0 / (rrf_k + rank))
        cur["vector_score"] = row.get("vector_score")
        cur.setdefault("retrieval_channels", [])
        if "vector" not in cur["retrieval_channels"]:
            cur["retrieval_channels"].append("vector")

    out = list(merged.values())
    out.sort(
        key=lambda r: (
            -float(r.get("rrf_score") or 0.0),
            _retrieval_rank_key(r),
        )
    )

    for row in out:
        row["final_score"] = float(row.get("rrf_score") or 0.0)
        row["score"] = row["final_score"]

    return diversify_results(out, limit)

def retrieve_chunks_for_message(
    *,
    conversation_id: str,
    user_message: str,
    limit: int = 8,
    cfg: RetrievalConfig | None = None,
) -> dict:
    cfg = cfg or load_retrieval_config()
    app_cfg = load_app_config()

    include_flags = {x.strip().upper() for x in (cfg.query_include or "").split(",") if x.strip()}
    do_fts = "FTS" in include_flags
    do_vector = "EMBEDDING" in include_flags
    if do_fts and do_vector:
        retrieval_mode = "hybrid"
    elif do_vector:
        retrieval_mode = "vector"
    elif do_fts:
        retrieval_mode = "fts"
    else:
        retrieval_mode = "none"

    debug: Dict = {
        #"query_mode": cfg.query_mode,
        "query_include": cfg.query_include,
        "include_globals": cfg.query_global_artifacts,
        "original_user_message": user_message,
        "retrieval_mode": retrieval_mode,
        "fts_enabled": do_fts,
        "vector_enabled": do_vector,
        "slices": [],
        "shapes": [],
        "search_queries": [],
        "llm_expand_enabled": cfg.llm_expand_enabled,
        "llm_expand_recommended": False,
        "llm_expand_terms": [],
        "cache_hit": False,
    }

    emb_cfg = load_embedding_config()
    vec_cfg = load_vector_config()

    # cache_key = (conversation_id, user_message.strip())
    cache_key = (
        conversation_id,
        user_message.strip(),
        cfg.query_include,
        cfg.query_expand_results,
        cfg.query_global_artifacts,
        cfg.query_include_project_conversation_transcripts,
        cfg.query_include_global_conversation_transcripts,
        cfg.query_include_recent_conversation_transcripts,
        cfg.recent_conversation_transcript_limit,
        app_cfg.search_chat_history,
        emb_cfg.provider,
        emb_cfg.model,
        vec_cfg.backend,
        vec_cfg.collection_name,
    )
    if (False):
        cache_key = (
            conversation_id,
            user_message.strip(),
            cfg.query_global_artifacts,
            cfg.query_include_project_conversation_transcripts,
            cfg.query_include_global_conversation_transcripts,
            cfg.query_include_recent_conversation_transcripts,
            cfg.recent_conversation_transcript_limit,
            app_cfg.search_chat_history,
        )

    cached = _cache_get(cache_key)
    if cached is not None:
        cached_results = cached.get("results") or []
        cached_raw_results = cached.get("raw_results") or []
        cached_debug = dict(cached.get("debug") or {})
        cached_debug["cache_hit"] = True

        return {
            "ok": True,
            "mode": cfg.query_include,
            "cached": True,
            "raw_results": cached_raw_results,
            "results": cached_results,
            "debug": cached_debug,
        }
    
    if (False):
        cached = _cache_get(cache_key)
        if cached is not None:
            return {
                "ok": True,
                "mode": cfg.query_include,
                #"mode": cfg.query_mode,
                "cached": True,
                "results": cached,
                "debug": {
                    "query_include": cfg.query_include,
                    "retrieval_mode": retrieval_mode,
                    "fts_enabled": do_fts,
                    "vector_enabled": do_vector,
                    "include_globals": cfg.query_global_artifacts,
                    "original_user_message": user_message,
                    "cache_hit": True,
                    "slices": [],
                    "shapes": [],
                    "search_queries": [],
                    "llm_expand_enabled": cfg.llm_expand_enabled,
                    "llm_expand_recommended": False,
                    "llm_expand_terms": [],            },
            }

    slices = slice_user_query(user_message, cfg=cfg)
    log_debug("RAG retrieve start: cid=%s include=%s slices=%d limit=%d msg_len=%d",
        conversation_id, cfg.query_include, len(slices), limit, len(user_message or ""))

    # First pass: FTS over each slice
    # merged: Dict[int, dict] = {}  # chunk_id -> best row
    
    fts_rows_all: List[dict] = []
    vector_rows_all: List[dict] = []
    raw_rows: List[dict] = []
    raw_counts_by_chunk: Dict[int, int] = {}
    raw_counts_by_artifact: Dict[str, int] = {}
    raw_counts_by_file: Dict[str, int] = {}

    per_slice_limit = max(3, limit)  # give each slice a chance
    for s in slices:
        if do_fts:
            # existing FTS code stays here
            qs = shape_fts_query(s, cfg)
            log_debug("RAG slice: text=%r fts=%r terms=%r phrases=%r",
            s[:160], qs.fts_query, qs.kept_terms, qs.kept_phrases)
            q = qs.fts_query or s
            debug["slices"].append(s[:160])
            debug["shapes"].append({"fts": qs.fts_query, "terms": qs.kept_terms, "phrases": qs.kept_phrases})
            debug["search_queries"].append(q)

            rows = []
            try:
                rows = search_corpus_for_conversation(
                    conversation_id=conversation_id,
                    query=q,
                    limit=per_slice_limit,
                    cfg=cfg,
                )
            except Exception as e:
                log_debug("RAG search failed for shaped query %r: %r", q, e)

            if not rows:
                safe_q = " ".join(f'"{tok.replace(chr(34), chr(34) * 2)}"' for tok in qs.kept_terms)
                if not safe_q and qs.kept_phrases:
                    safe_q = " ".join(f'"{p.replace(chr(34), chr(34) * 2)}"' for p in qs.kept_phrases)

                if safe_q or s:
                    retry_q = safe_q or s
                    log_debug("RAG retry search: query=%r", retry_q)
                    rows = search_corpus_for_conversation(
                        conversation_id=conversation_id,
                        query=retry_q,
                        limit=per_slice_limit,
                        cfg=cfg,
                    )

            log_debug("RAG search: query=%r returned=%d", q, len(rows))
            for r in rows:
                row = dict(r)
                row["fts_score"] = float(row.get("score") or 0.0)
                row["vector_score"] = None
                row["rrf_score"] = None
                row["final_score"] = None
                row["retrieval_channels"] = ["fts"]

                raw_rows.append(row)
                fts_rows_all.append(row)

                cid = int(row["chunk_id"])
                raw_counts_by_chunk[cid] = raw_counts_by_chunk.get(cid, 0) + 1

                aid = (row.get("artifact_id") or "").strip()
                if aid:
                    raw_counts_by_artifact[aid] = raw_counts_by_artifact.get(aid, 0) + 1

                fid = (row.get("file_id") or "").strip()
                if fid:
                    raw_counts_by_file[fid] = raw_counts_by_file.get(fid, 0) + 1

                #if cid not in merged or _retrieval_rank_key(row) < _retrieval_rank_key(merged[cid]):
                #    merged[cid] = row
        if do_vector:
            try:
                vrows = _retrieve_vector_rows_for_query(
                    conversation_id=conversation_id,
                    query_text=s,
                    limit=per_slice_limit,
                    cfg=cfg,
                )
            except Exception as e:
                log_debug("Vector retrieval failed for query %r: %r", s, e)
                vrows = []

            for r in vrows:
                raw_rows.append(r)
                vector_rows_all.append(r)

    raw_result_count = len(raw_rows)

    # Results list
    fts_rows = []
    if do_fts:
        fts_merged: Dict[int, dict] = {}
        for r in fts_rows_all:
            cid = int(r["chunk_id"])
            if cid not in fts_merged or _retrieval_rank_key(r) < _retrieval_rank_key(fts_merged[cid]):
                fts_merged[cid] = r
        fts_rows = list(fts_merged.values())
        fts_rows.sort(key=_retrieval_rank_key)
        
    vector_rows = []
    if do_vector:
        vector_best: Dict[int, dict] = {}
        for r in vector_rows_all:
            cid = int(r["chunk_id"])
            if cid not in vector_best or float(r.get("vector_score") or 0.0) > float(vector_best[cid].get("vector_score") or 0.0):
                vector_best[cid] = r
        vector_rows = list(vector_best.values())
        vector_rows.sort(key=lambda r: float(r.get("vector_score") or 0.0), reverse=True)

    before_diversify_count = len(fts_rows) + len(vector_rows)
    if do_fts and do_vector:
        results = _rrf_merge(fts_rows=fts_rows, vector_rows=vector_rows, limit=limit)
    elif do_vector:
        results = diversify_results(vector_rows, limit)
    else:
        results = diversify_results(fts_rows, limit)

    if (False):
        results = list(merged.values())
        #results.sort(key=lambda r: r.get("score", 1e9))
        results.sort(key=_retrieval_rank_key)

        before_diversify_count = len(results)
        results = diversify_results(results, limit)
    
    after_diversify_count = len(results)
    # Report pre/post result counts
    debug["raw_result_count"] = raw_result_count
    debug["result_count_before_diversify"] = before_diversify_count
    debug["result_count_after_diversify"] = after_diversify_count
    debug["fts_result_count"] = len(fts_rows)
    debug["vector_result_count"] = len(vector_rows)
    # Report raw counts by asset type
    debug["raw_counts_by_chunk"] = raw_counts_by_chunk
    debug["raw_counts_by_artifact"] = raw_counts_by_artifact
    debug["raw_counts_by_file"] = raw_counts_by_file
    # Report dominance metrics by asset type
    debug["dominance"] = {
        "top_files_by_raw_hits": sorted(raw_counts_by_file.items(), key=lambda kv: kv[1], reverse=True)[:10],
        "top_artifacts_by_raw_hits": sorted(raw_counts_by_artifact.items(), key=lambda kv: kv[1], reverse=True)[:10],
        "top_chunks_by_raw_hits": sorted(raw_counts_by_chunk.items(), key=lambda kv: kv[1], reverse=True)[:10],
    }

    # Heuristic LLM expansion hook (placeholder): only if enabled and low signal/low results.
    # We’ll wire the LLM call next, once you decide where it lives (main.py vs a helper module).
    if cfg.llm_expand_enabled:
        # count “signal terms” from the first slice’s shaper as a proxy
        first_shape = shape_fts_query(slices[0], cfg) if slices else None
        term_count = len(first_shape.kept_terms) + len(first_shape.kept_phrases) if first_shape else 0
        llm_expand_recommended = (term_count < cfg.llm_expand_min_terms or len(results) < cfg.llm_expand_min_results)
        log_debug("RAG LLM assist: term_count=%s llm_expand_recommended=%s",
            term_count, llm_expand_recommended)
        debug["llm_expand_recommended"] = llm_expand_recommended
        debug["llm_expand_reason"] = (
            f"term_count={term_count}, results={len(results)}, "
            f"min_terms={cfg.llm_expand_min_terms}, min_results={cfg.llm_expand_min_results}"
        )

    log_debug("RAG final: results=%d cache=%s",
        len(results), False)
    #_cache_put(cache_key, results, cfg.retrieval_cache_ttl_sec, cfg.retrieval_cache_max_entries)
    _cache_put(
        cache_key,
        {
            "raw_results": raw_rows,
            "results": results,
            "debug": debug,
        },
        cfg.retrieval_cache_ttl_sec,
        cfg.retrieval_cache_max_entries,
    )

    return {
        "ok": True,
        "mode": cfg.query_include,
        "cached": False,
        "raw_results": raw_rows,
        "results": results,
        "debug": debug,
    }
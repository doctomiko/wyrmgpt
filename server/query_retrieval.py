# server/retrieval.py
import time
from collections import OrderedDict
from typing import Dict, List, Tuple

from .config import QueryConfig, load_query_config, load_app_config
from .query_slicer import slice_user_query
from .query_shaper import shape_fts_query
from .logging_helper import log_debug
from .db import search_corpus_for_conversation  # your existing function

# Simple TTL LRU cache: key -> (expires_at, results)
_CACHE: "OrderedDict[Tuple[str,str], Tuple[float, List[dict]]]" = OrderedDict()

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

def retrieve_chunks_for_message(
    *,
    conversation_id: str,
    user_message: str,
    limit: int = 8,
    cfg: QueryConfig | None = None,
    # include_global: bool = False,
) -> dict:
    cfg = cfg or load_query_config()
    app_cfg = load_app_config()

    #debug: Dict = {"slices": [], "shapes": []}
    debug: Dict = {
        "query_mode": cfg.query_mode,
        "include_globals": cfg.query_global_artifacts,
        "original_user_message": user_message,
        "slices": [],
        "shapes": [],
        "search_queries": [],
        "llm_expand_enabled": cfg.llm_expand_enabled,
        "llm_expand_recommended": False,
        "llm_expand_terms": [],
        "cache_hit": False,
    }
    # cache_key = (conversation_id, user_message.strip())
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
        return {
            "ok": True,
            "mode": cfg.query_mode,
            "cached": True,
            "results": cached,
            "debug": {
                "query_mode": cfg.query_mode,
                "include_globals": cfg.query_global_artifacts,
                "original_user_message": user_message,
                "cache_hit": True,
                "slices": [],
                "shapes": [],
                "search_queries": [],
                "llm_expand_enabled": cfg.llm_expand_enabled,
                "llm_expand_recommended": False,
                "llm_expand_terms": [],
            },
        }

    slices = slice_user_query(user_message, cfg=cfg)
    log_debug("RAG retrieve start: cid=%s mode=%s slices=%d limit=%d msg_len=%d",
        conversation_id, cfg.query_mode, len(slices), limit, len(user_message or ""))

    # First pass: FTS over each slice
    merged: Dict[int, dict] = {}  # chunk_id -> best row
    raw_rows: List[dict] = []
    raw_counts_by_chunk: Dict[int, int] = {}
    raw_counts_by_artifact: Dict[str, int] = {}
    raw_counts_by_file: Dict[str, int] = {}

    per_slice_limit = max(3, limit)  # give each slice a chance
    for s in slices:
        qs = shape_fts_query(s, cfg)
        log_debug("RAG slice: text=%r fts=%r terms=%r phrases=%r",
          s[:160], qs.fts_query, qs.kept_terms, qs.kept_phrases)
        q = qs.fts_query or s
        debug["slices"].append(s[:160])
        debug["shapes"].append({"fts": qs.fts_query, "terms": qs.kept_terms, "phrases": qs.kept_phrases})
        debug["search_queries"].append(q)
        rows = search_corpus_for_conversation(
            conversation_id=conversation_id,
            query=q,
            limit=per_slice_limit,
            cfg=cfg,
        )
        log_debug("RAG search: query=%r returned=%d", q, len(rows))
        for r in rows:
            raw_rows.append(r)
            # count chunks
            cid = int(r["chunk_id"])
            raw_counts_by_chunk[cid] = raw_counts_by_chunk.get(cid, 0) + 1
            # count artifacts
            aid = (r.get("artifact_id") or "").strip()
            if aid:
                raw_counts_by_artifact[aid] = raw_counts_by_artifact.get(aid, 0) + 1
            # count files
            fid = (r.get("file_id") or "").strip()
            if fid:
                raw_counts_by_file[fid] = raw_counts_by_file.get(fid, 0) + 1
            # keep best (lowest) score per chunk for final result set
            if cid not in merged or r.get("score", 1e9) < merged[cid].get("score", 1e9):
                merged[cid] = r

    # count(chunks per file_id) >= QUERY_INCLUDE_FILE_MATCH_COUNT
    # count(chunks per artifact_id) >= QUERY_INCLUDE_ARTICLE_MATCH_COUNT
    # count(chunks per conversation_id) >= QUERY_INCLUDE_CONVO_MATCH_COUNT

    raw_result_count = len(raw_rows)

    results = list(merged.values())
    results.sort(key=lambda r: r.get("score", 1e9))

    before_diversify_count = len(results)
    results = diversify_results(results, limit)
    after_diversify_count = len(results)
    # Report pre/post result counts
    debug["raw_result_count"] = raw_result_count
    debug["result_count_before_diversify"] = before_diversify_count
    debug["result_count_after_diversify"] = after_diversify_count
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
    _cache_put(cache_key, results, cfg.retrieval_cache_ttl_sec, cfg.retrieval_cache_max_entries)
    return {
        "ok": True,
        "mode": cfg.query_mode,
        "cached": False,
        "raw_results": raw_rows,
        "results": results,
        "debug": debug,
    }
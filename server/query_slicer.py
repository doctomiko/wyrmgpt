# server/query_slicer.py
import re
from typing import List
from .config import RetrievalConfig, load_retrieval_config

def slice_user_query(text: str, cfg: RetrievalConfig | None = None) -> List[str]:
    cfg = cfg or load_retrieval_config()
    # max_slices: int = 6, long_query_chars: int = 400
    t = (text or "").strip()
    if not t:
        return []
    if len(t) < cfg.long_query_chars:
        return [t]

    # Prefer paragraphs
    paras = [p.strip() for p in re.split(r"\n\s*\n+", t) if p.strip()]
    if len(paras) == 1:
        # fallback: sentence-ish splits
        paras = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", t)
        paras = [p.strip() for p in paras if p.strip()]

    # Cap and keep the best slices by “density” (longer + not just stopwords)
    # Simple heuristic: prefer medium chunks, avoid super tiny ones.
    paras.sort(key=lambda s: (min(len(s), 800), len(s)), reverse=True)
    selected = paras[:cfg.max_query_slices]

    # Preserve original order by using their index in the original text
    selected.sort(key=lambda s: t.find(s))
    return selected
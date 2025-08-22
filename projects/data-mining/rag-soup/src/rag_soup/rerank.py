import math
from .schemas import Chunk


def combine_scores(item, cross: float, w=None) -> float:
    w = w or {"cross": 1.2, "dense": 0.6, "bm25": 0.3, "auth": 0.2, "len": 0.1, "rec": 0.2}
    dense = getattr(item, "dense_sim", 0.0) or 0.0
    bm25 = getattr(item, "bm25", 0.0) or 0.0
    auth = getattr(item, "authority", 0.0) or 0.0
    length_pen = getattr(item, "length", 0) or 0
    recency = (getattr(item, "recency_days", 365.0) or 365.0) / 30.0
    raw = (
        w["cross"] * cross
        + w["dense"] * dense
        + w["bm25"] * bm25
        + w["auth"] * auth
        - w["len"] * length_pen
        - w["rec"] * recency
    )
    return 1 / (1 + math.exp(-raw))

from typing import Dict
from .schemas import Chunk


class SafetyAdapter:
    """Pluggable scoring + routing. Swap regex with ML later."""

    def __init__(self, thresholds: Dict[str, float]):
        self.t = thresholds

    def score_text(self, txt: str) -> Dict[str, float]:
        # default noop; see mine_dump for the simple regex impl
        return {"nsfw": 0.0, "toxicity": 0.0, "illicit": 0.0, "pii": 0.0, "conf": 0.0}

    def route(self, doc_scores: Dict[str, float]) -> Dict[str, str | list]:
        reasons = []
        for k in ("illicit", "nsfw", "toxicity", "pii"):
            if doc_scores.get(k, 0.0) >= self.t.get(k, 1.0):
                reasons.append(k)
        zone = "red_quarantine" if reasons else "silver_normalized"
        return {"zone": zone, "reasons": reasons}

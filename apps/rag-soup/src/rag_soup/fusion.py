def rrf(rankings: list[dict[str, int]], k: int = 60, weights: list[float] | None = None):
    ws = weights or [1 / len(rankings)] * len(rankings)
    scores = {}
    for w, r in zip(ws, rankings):
        for d, rk in r.items():
            scores[d] = scores.get(d, 0.0) + w * (1.0 / (k + rk))
    return sorted(scores.items(), key=lambda x: -x[1])


def z_fuse(score_dicts: list[dict[str, float]], weights: list[float] | None = None):
    docs = set().union(*[d.keys() for d in score_dicts])
    ws = weights or [1 / len(score_dicts)] * len(score_dicts)
    fused = {d: 0.0 for d in docs}
    for w, scores in zip(ws, score_dicts):
        if not scores:
            continue
        vals = list(scores.values())
        mu = sum(vals) / len(vals)
        sigma = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
        floor = (min(vals) - mu) / sigma
        for d in docs:
            z = (scores[d] - mu) / sigma if d in scores else floor
            fused[d] += w * z
    return sorted(fused.items(), key=lambda x: -x[1])

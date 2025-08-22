def mmr_select(items, scores, k=10, lam=0.7, sim=None, cap_per_doc=2):
    sim = sim or (lambda a, b: 0.0)
    selected, selected_ids, per_doc = [], set(), {}
    cand = sorted(items, key=lambda x: -scores[x.chunk_id])
    while cand and len(selected) < k:
        best = None
        best_score = -1
        for it in cand:
            if per_doc.get(it.doc_uid, 0) >= cap_per_doc:
                continue
            rel = scores[it.chunk_id]
            div = max(sim(it, s) for s in selected) if selected else 0.0
            sc = lam * rel - (1 - lam) * div
            if sc > best_score:
                best, best_score = it, sc
        if not best:
            break
        selected.append(best)
        selected_ids.add(best.chunk_id)
        per_doc[best.doc_uid] = per_doc.get(best.doc_uid, 0) + 1
        cand = [c for c in cand if c.chunk_id not in selected_ids]
    return selected

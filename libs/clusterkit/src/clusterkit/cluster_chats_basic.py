#!/usr/bin/env python3
"""Cluster chat pairs using a tiny pure-Python pipeline.

Usage
-----
Run the script directly and supply a JSONL file of chat pairs::

    python cluster_chats_basic.py --jsonl chats.jsonl --k 5 --max-examples 3

Arguments
~~~~~~~~~
``--jsonl``
    Path to a JSON Lines file where each line contains a conversation turn
    encoded as a JSON object.  Every object must provide the keys ``"user"``
    and ``"assistant"`` whose values are strings.

``--k``
    Number of clusters to produce.  Defaults to ``5``.

``--max-examples``
    Maximum number of representative chats to print for each cluster.  Defaults
    to ``5``.

Input format
------------
Each line in the JSONL file should look like::

    {"user": "How are you?", "assistant": "I'm well, thank you."}

This module avoids heavy dependencies like numpy or scikit-learn.  It provides
very small bag-of-words embeddings and a simple K-Means implementation to group
similar conversation turns.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Sequence

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_texts(jsonl_path: Path) -> List[str]:
    """Load user/assistant pairs from *jsonl_path* and join them."""
    texts: List[str] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            texts.append(f"User: {data['user']}\nAssistant: {data['assistant']}")
    return texts

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def build_vocab(texts: Sequence[str]) -> Dict[str, int]:
    vocab: Dict[str, int] = {}
    for text in texts:
        for token in text.lower().split():
            if token not in vocab:
                vocab[token] = len(vocab)
    return vocab


def embed_texts(texts: Sequence[str], vocab: Dict[str, int]) -> List[List[float]]:
    vectors: List[List[float]] = []
    for text in texts:
        vec = [0.0] * len(vocab)
        for token in text.lower().split():
            vec[vocab[token]] += 1.0
        vectors.append(vec)
    return vectors

# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def _sqdist(a: Sequence[float], b: Sequence[float]) -> float:
    return sum((ai - bi) ** 2 for ai, bi in zip(a, b))


def cluster_vectors(vectors: List[List[float]], k: int, iters: int = 10) -> List[int]:
    """Very small K-Means returning label indices for *vectors*."""
    centroids = [vectors[0][:]]
    while len(centroids) < k:
        idx = max(
            range(len(vectors)),
            key=lambda i: min(_sqdist(vectors[i], c) for c in centroids),
        )
        centroids.append(vectors[idx][:])
    labels = [0] * len(vectors)
    for _ in range(iters):
        for idx, vec in enumerate(vectors):
            labels[idx] = min(range(k), key=lambda j: _sqdist(vec, centroids[j]))
        for j in range(k):
            members = [v for v, lbl in zip(vectors, labels) if lbl == j]
            if members:
                centroids[j] = [sum(vals) / len(members) for vals in zip(*members)]
    return labels


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def inspect_clusters(texts: List[str], labels: Sequence[int], max_examples: int = 5) -> None:
    clusters: Dict[int, List[str]] = {}
    for text, lbl in zip(texts, labels):
        clusters.setdefault(lbl, []).append(text)
    for lbl, items in clusters.items():
        print(f"\nCluster {lbl} ({len(items)} items)")
        for t in items[:max_examples]:
            preview = (t[:117] + "…") if len(t) > 120 else t
            print(" •", preview)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cluster chats with tiny K-Means")
    p.add_argument("--jsonl", type=Path, required=True, help="conversation_turns.jsonl")
    p.add_argument("--k", type=int, default=5, help="number of clusters")
    p.add_argument("--max-examples", type=int, default=5, help="examples per cluster")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    texts = load_texts(args.jsonl)
    vocab = build_vocab(texts)
    vectors = embed_texts(texts, vocab)
    labels = cluster_vectors(vectors, args.k)
    inspect_clusters(texts, labels, args.max_examples)


if __name__ == "__main__":
    main()

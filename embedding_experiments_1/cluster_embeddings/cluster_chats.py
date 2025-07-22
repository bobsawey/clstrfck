#!/usr/bin/env python3
"""
cluster_chats.py
================
Embed chat-turn pairs with a GGUF embedding model (via llama-cpp-python) and
cluster the resulting vectors with scikit-learn K-Means.

Author : 2025-07-22

bobsawey + o3
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from tqdm import tqdm

try:
    from llama_cpp import Llama
except ImportError:
    sys.stderr.write(
        "FATAL: llama-cpp-python is not installed.\n"
        "   pip install llama-cpp-python\n"
    )
    sys.exit(1)

# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────
def load_texts(jsonl_path: Path) -> List[str]:
    """Return a list of concatenated user+assistant strings."""
    if not jsonl_path.is_file():
        raise FileNotFoundError(jsonl_path)

    texts: List[str] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            try:
                data = json.loads(line)
                texts.append(f"User: {data['user']}\nAssistant: {data['assistant']}")
            except (json.JSONDecodeError, KeyError) as err:
                logging.warning("Skipping bad line %d: %s", i, err)

    if not texts:
        raise ValueError("No valid lines found in JSONL.")
    return texts


def init_llm(model_path: Path, n_threads: int, n_batch: int) -> Llama:
    """Initialise llama-cpp model in embedding mode."""
    if not model_path.is_file():
        raise FileNotFoundError(model_path)

    logging.info("Loading model %s …", model_path)
    llm = Llama(
        model_path=str(model_path),
        embedding=True,
        n_threads=n_threads,
        n_batch=n_batch,
        logits_all=False,
    )
    logging.info("Model loaded. embedding_length=%d", llm.metadata["qwen3.embedding_length"] if "qwen3.embedding_length" in llm.metadata else llm.n_embd)
    return llm


def sentence_embed(
    llm: Llama,
    text: str,
    output_dim: int | None = None,
) -> np.ndarray:
    """Embed one text and mean-pool the per-token vectors to a 1-D sentence vector."""
    sig = llm.create_embedding.__signature__  # type: ignore[attr-defined]
    kwargs = {}
    if output_dim is not None and "output_dimension" in sig.parameters:
        kwargs["output_dimension"] = output_dim

    resp = llm.create_embedding([text], **kwargs)
    token_vecs = np.asarray(resp["data"][0]["embedding"], dtype=np.float32)
    # shape: (tokens, dim)
    return token_vecs.mean(axis=0)


def embed_corpus(
    llm: Llama,
    texts: List[str],
    output_dim: int | None,
    dump_jsonl: Path | None,
) -> np.ndarray:
    """Embed every text; optionally dump `{text, embedding}` lines."""
    if dump_jsonl:
        dump_file = dump_jsonl.open("w", encoding="utf-8")
    else:
        dump_file = None

    vectors = []
    for text in tqdm(texts, desc="Embedding"):
        vec = sentence_embed(llm, text, output_dim)
        vectors.append(vec)
        if dump_file:
            dump_file.write(json.dumps({"text": text, "embedding": vec.tolist()}) + "\n")

    if dump_file:
        dump_file.close()

    return np.stack(vectors)  # (N, dim)


def choose_best_k(x: np.ndarray, k_min: int, k_max: int) -> int:
    best_k, best_score = k_min, -1.0
    for k in range(k_min, k_max + 1):
        km = KMeans(n_clusters=k, random_state=42, n_init="auto").fit(x)
        score = silhouette_score(x, km.labels_)
        logging.info("K=%d  silhouette=%.4f", k, score)
        if score > best_score:
            best_k, best_score = k, score
    logging.info("Best K by silhouette: %d (%.4f)", best_k, best_score)
    return best_k


def inspect_clusters(texts: List[str], labels: np.ndarray, max_examples: int = 5) -> None:
    clusters = {}
    for idx, lbl in enumerate(labels):
        clusters.setdefault(lbl, []).append(texts[idx])

    for lbl, items in clusters.items():
        print(f"\nCluster {lbl} ({len(items)} items)")
        for t in items[:max_examples]:
            preview = (t[:117] + "…") if len(t) > 120 else t
            print(" •", preview)


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Embed + cluster chat turns.")
    p.add_argument("--jsonl", required=True, type=Path, help="conversation_turns.jsonl")
    p.add_argument("--model", required=True, type=Path, help="GGUF model file")
    p.add_argument("--threads", type=int, default=os.cpu_count() or 4, help="CPU threads")
    p.add_argument("--batch", type=int, default=1024, help="n_batch (token chunk size)")
    p.add_argument("--output-dim", type=int, default=None, help="Down-project dim (if model supports)")
    p.add_argument("--dump-embeddings", type=Path, help="Optional JSONL to save text+embedding")
    p.add_argument("--best-k", action="store_true", help="Silhouette sweep to pick K")
    p.add_argument("--k", type=int, default=5, help="Fixed K if --best-k not used")
    p.add_argument("--k-min", type=int, default=2)
    p.add_argument("--k-max", type=int, default=10)
    p.add_argument("--max-examples", type=int, default=5)
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    try:
        texts = load_texts(args.jsonl)
        llm = init_llm(args.model, args.threads, args.batch)
        embeddings = embed_corpus(
            llm,
            texts,
            args.output_dim,
            args.dump_embeddings,
        )

        k = choose_best_k(embeddings, args.k_min, args.k_max) if args.best_k else args.k
        labels = KMeans(n_clusters=k, random_state=42, n_init="auto").fit_predict(embeddings)
        inspect_clusters(texts, labels, args.max_examples)

    except Exception as err:
        logging.critical("Aborted: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()

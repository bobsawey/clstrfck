#!/usr/bin/env python3
"""Extract and cluster code snippets from chat transcripts.

The script understands two simple chat formats:

* OpenAI-style chat logs where a JSON file contains a top-level ``messages``
  list with ``{"role": ..., "content": ...}`` dictionaries.
* Line-oriented JSONL files where each line is one such dictionary.

For every message the script searches for fenced code blocks (````` … `````).
The code blocks are indexed with their message number and byte offset so that
callers can recover the surrounding context.  A tiny bag-of-words embedding and
K-Means implementation from :mod:`cluster_chats_basic` is then used to group
similar snippets.

This is only a proof-of-concept.  In a larger system one could replace the
regular-expression based code finder with a more robust engine such as
``tree-sitter`` or ``Pygments``' language guesser which are able to detect even
small fragments of many languages.  Another future direction is training a
lightweight classifier to tag lines of a chat transcript as "code" or "prose".
Such a model could recover snippets even when the original conversation lacks
fences entirely, offering a second, more resilient alternative to the current
regex approach.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from .cluster_chats_basic import build_vocab, embed_texts, cluster_vectors

CODE_FENCE_RE = re.compile(r"```(?:\w+)?\n(.*?)```", re.DOTALL)


@dataclass
class CodeSpan:
    """A code snippet extracted from a message."""

    message_index: int
    start: int
    end: int
    code: str


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def load_messages(path: Path) -> List[str]:
    """Return a list of message strings from *path*.

    ``path`` may point to a JSON file with ``{"messages": [...]}`` or a JSONL
    file with one message per line.
    """

    if not path.exists():
        raise FileNotFoundError(path)

    texts: List[str] = []
    if path.suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                data = json.loads(line)
                texts.append(str(data["content"]))
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        msgs = data.get("messages", [])
        for msg in msgs:
            texts.append(str(msg["content"]))
    return texts


# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------

def extract_code_spans(messages: Sequence[str]) -> List[CodeSpan]:
    spans: List[CodeSpan] = []
    for idx, msg in enumerate(messages):
        for m in CODE_FENCE_RE.finditer(msg):
            start, end = m.span(1)
            spans.append(CodeSpan(idx, start, end, m.group(1)))
    return spans


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def cluster_code_spans(spans: Sequence[CodeSpan], k: int) -> List[int]:
    texts = [s.code for s in spans]
    vocab = build_vocab(texts)
    vectors = embed_texts(texts, vocab)
    return cluster_vectors(vectors, k)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def inspect_clusters(spans: Sequence[CodeSpan], labels: Sequence[int], max_examples: int) -> None:
    clusters: dict[int, List[CodeSpan]] = {}
    for span, label in zip(spans, labels):
        clusters.setdefault(label, []).append(span)
    for label, items in clusters.items():
        print(f"\nCluster {label} ({len(items)} items)")
        for span in items[:max_examples]:
            preview = span.code.strip().splitlines()[0]
            print(f" • msg={span.message_index} offset={span.start}: {preview}")

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cluster code snippets from chats")
    p.add_argument("--input", type=Path, required=True, help="chat.json or chat.jsonl")
    p.add_argument("--k", type=int, default=5, help="number of clusters")
    p.add_argument("--max-examples", type=int, default=5)
    return p.parse_args()

def main() -> None:
    args = parse_args()
    messages = load_messages(args.input)
    spans = extract_code_spans(messages)
    if not spans:
        print("No code blocks found.")
        return
    labels = cluster_code_spans(spans, args.k)
    inspect_clusters(spans, labels, args.max_examples)

if __name__ == "__main__":
    main()

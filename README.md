# clstrfck

Utilities and experiments for clustering chat conversations.

## Embedding and clustering

The `embedding_experiments_1/cluster_embeddings/` package contains two scripts:

- `cluster_chats.py` — embed user/assistant turns with a GGUF embedding model served by `llama-cpp-python` and cluster vectors using scikit-learn K‑Means. It can sweep a range of cluster counts with silhouette scoring and optionally save embeddings.

  ```sh
  python embedding_experiments_1/cluster_embeddings/cluster_chats.py \
    --jsonl conversation_turns.jsonl \
    --model /path/to/bge-base-en-v1.5.Q4_K_M.gguf \
    --best-k --verbose
  ```

- `cluster_chats_basic.py` — a tiny, pure‑Python pipeline that builds a bag‑of‑words vocabulary, creates term‑frequency vectors, and groups them with a lightweight K‑Means. Designed for quick experiments without heavy dependencies.

## Tools

The `tools/` directory hosts miscellaneous helpers:

- **Chat Conversation Viewer:** `chat_conversation_viewer_single_page_tool.html` with documentation in `readme_chat_conversation_viewer_single_page_tool.md`. Open the HTML file in a browser to inspect ChatGPT conversation exports and optionally export SFT‑style JSONL.
- **RLHF data generator:** `generate_rlhf.py` parses conversation dumps and emits SFT segments, DPO pairs, and tool‑usage logs.

## Reference material

Reference documents intended for future data‑mining live in `docs/reference/`.

## Tests

A small pytest suite covers the pure‑Python clustering helpers.

```sh
pytest
```

## License

Apache 2.0 — see [LICENSE](LICENSE).

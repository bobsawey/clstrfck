# clstrfck

Utilities and experiments for clustering chat conversations.

## Embedding and clustering

The `embedding_experiments_1/cluster_embeddings/` package contains two scripts.
Both consume a JSONL of chat pairs where each line looks like:

```json
{"user": "How are you?", "assistant": "I'm well, thank you."}
```

- `cluster_chats.py` — embed user/assistant turns with a GGUF embedding model served by `llama-cpp-python` and cluster vectors using scikit-learn K‑Means. It can sweep a range of cluster counts with silhouette scoring and optionally save embeddings. Outputs cluster assignments to stdout and, with `--dump-embeddings`, writes `{ "text": ..., "embedding": [...] }` lines to a JSONL.

  ```sh
  python embedding_experiments_1/cluster_embeddings/cluster_chats.py \
    --jsonl conversation_turns.jsonl \
    --model /path/to/bge-base-en-v1.5.Q4_K_M.gguf \
    --best-k --verbose
  ```

- `cluster_chats_basic.py` — a tiny, pure‑Python pipeline that builds a bag‑of‑words vocabulary, creates term‑frequency vectors, and groups them with a lightweight K‑Means. Designed for quick experiments without heavy dependencies. Prints cluster previews to the terminal.

## Tools

The `tools/` directory hosts miscellaneous helpers:

- **Chat Conversation Viewer:** `chat_conversation_viewer_single_page_tool.html` with documentation in `readme_chat_conversation_viewer_single_page_tool.md`. Open the HTML file in a browser and load ChatGPT `.json` exports. You can browse turns and export an SFT JSONL where each line is:

  ```json
  {"messages": [{"role": "user", "content": "…"}], "meta": {"conv_id": "…", "seq": 12}}
  ```

- **RLHF data generator:** `generate_rlhf.py` consumes the same ChatGPT dumps and writes an output directory containing:
  - `sft.jsonl` — segment lines in the viewer format above,
  - `dpo_pairs.jsonl` — `{prompt, rejected, chosen, meta}` triples,
  - `tool_traces.jsonl` — `{conv_id, seq, tool_name, direction, payload, text_preview, urls, time}` rows.

## Reference material

Reference documents intended for future data‑mining live in `docs/reference/`.

## Tests

A small pytest suite covers the pure‑Python clustering helpers.

```sh
pytest
```

## License

Apache 2.0 — see [LICENSE](LICENSE).

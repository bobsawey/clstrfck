
# 📓
- 💿 loads user 🧑🏻 + assistant 🤖 pairs from a JSONL file
  - prepping pairs will be its own directory of stuff ( TODO: add SALON/openai_chatpair_prep )
- 🎛️ embeds each pair with any GGUF embedding model served by llama-cpp-python
- ⚖️ mean-pools the per-token vectors to get a single sentence embedding
  - TODO: ELABORATE. we may jave functionality issues due to misunderstandingZ
- (optionally) writes every {text, embedding} pair to a JSONL side-file
- 🥞 stacks the embeddings into a NumPy matrix
- 📑 clusters them with K-Means (automatic K sweep optional)
- 🖨️ prints a few examples from each cluster



# ⌨️

```shell
python cluster_chats.py \
  --jsonl conversation_turns.jsonl \
  --model /path/to/bge-base-en-v1.5.Q4_K_M.gguf \
  --batch 1024 \
  --best-k --verbose
```

---

Swap --model for any embedding GGUF you prefer.

Raise or lower --batch as long as it exceeds your longest prompt tokens.

--dump-embeddings out.jsonl will save every {text, embedding} line.

---

happy clustering!

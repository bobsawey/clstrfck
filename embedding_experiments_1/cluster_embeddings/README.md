
•	loads user + assistant pairs from a JSONL file
•	embeds each pair with any GGUF embedding model served by llama-cpp-python
•	mean-pools the per-token vectors to get a single sentence embedding
	•	(optionally) writes every {text, embedding} pair to a JSONL side-file
	•	stacks the embeddings into a NumPy matrix
	•	clusters them with K-Means (automatic K sweep optional)
	•	prints a few examples from each cluster



# ⌨️

python cluster_chats.py \
  --jsonl conversation_turns.jsonl \
  --model /path/to/bge-base-en-v1.5.Q4_K_M.gguf \
  --batch 1024 \
  --best-k --verbose

	•	Swap --model for any embedding GGUF you prefer.
	•	Raise or lower --batch as long as it exceeds your longest prompt tokens.
	•	--dump-embeddings out.jsonl will save every {text, embedding} line.

This version avoids every issue we debugged:
	•	uses a list for create_embedding
	•	mean-pools token vectors → fixed-length row
	•	catches JSON errors
	•	optional down-projection (output_dim) if model supports it
	•	simple, restart-safe JSONL dump

Happy clustering!

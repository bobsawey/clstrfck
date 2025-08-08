from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from embedding_experiments_1.cluster_embeddings.cluster_chats_basic import (
    load_texts,
    build_vocab,
    embed_texts,
    cluster_vectors,
)


def test_load_texts(tmp_path: Path) -> None:
    sample = tmp_path / "sample.jsonl"
    sample.write_text(
        '{"user": "hi", "assistant": "hello"}\n'
        '{"user": "bye", "assistant": "see you"}\n',
        encoding="utf-8",
    )
    texts = load_texts(sample)
    assert texts == [
        "User: hi\nAssistant: hello",
        "User: bye\nAssistant: see you",
    ]


def test_cluster_vectors() -> None:
    texts = [
        "User: I love cats\nAssistant: Cats are great pets",
        "User: Cats are amazing\nAssistant: Indeed, cats rule the internet",
        "User: My computer crashes\nAssistant: Try rebooting your PC",
        "User: I need a new keyboard\nAssistant: Mechanical keyboards are durable",
    ]
    vocab = build_vocab(texts)
    vectors = embed_texts(texts, vocab)
    labels = cluster_vectors(vectors, k=2)
    assert len(set(labels)) == 2
    assert labels[0] == labels[1]
    # at least one of the remaining items should belong to the other cluster
    assert labels[0] != labels[2] or labels[0] != labels[3]

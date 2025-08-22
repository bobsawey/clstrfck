from pathlib import Path

from clusterkit.index_code_snippets import (
    load_messages,
    extract_code_spans,
    cluster_code_spans,
)


def test_extract_code_spans(tmp_path: Path) -> None:
    sample = tmp_path / "sample.jsonl"
    sample.write_text(
        '{"content": "Here is code: \\n```python\\nprint(1)\\n```"}\n'
        '{"content": "No code"}\n',
        encoding="utf-8",
    )
    messages = load_messages(sample)
    spans = extract_code_spans(messages)
    assert len(spans) == 1
    span = spans[0]
    assert span.message_index == 0
    assert "print(1)" in span.code


def test_cluster_code_spans() -> None:
    messages = [
        "first```python\nprint('hi')\n```",
        "second```python\nprint('hi')\n```",
        "```javascript\nconsole.log('x')\n```",
    ]
    spans = extract_code_spans(messages)
    labels = cluster_code_spans(spans, k=2)
    assert labels[0] == labels[1]
    assert labels[0] != labels[2]

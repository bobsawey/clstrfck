"""Stage 3 model backend: LangExtract wiring.

Defines the extraction schema (prompt + few-shot examples) for the five
classes in this pass -- decision, task, claim, question, reference -- and
wraps `langextract.extract()` behind a small, swappable interface
(`Extractor` protocol) so tests can substitute a fake model without a live
API key while still exercising the real deterministic grounding logic in
extract.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

PROMPT_DESCRIPTION = """
Extract five kinds of load-bearing statements from the text, using the
exact wording found in the source for each extraction (do not paraphrase):

- decision: a choice that was made or settled on
- task: an action someone is meant to perform, often with a deadline
- claim: a falsifiable assertion about how something is or behaves
- question: an open question that has not been answered in the text
- reference: a citation, URL, or pointer to another document

Extract entities in the order they appear. Use exact text from the
document for extraction_text -- do not paraphrase or merge separate
sentences into one extraction.
""".strip()


def _example(text: str, spans: list[tuple[str, str, dict | None]]):
    import langextract as lx

    return lx.data.ExampleData(
        text=text,
        extractions=[
            lx.data.Extraction(
                extraction_class=cls,
                extraction_text=extraction_text,
                attributes=attrs,
            )
            for cls, extraction_text, attrs in spans
        ],
    )


def build_examples():
    return [
        _example(
            "We decided to use SQLite for the index. Benchmark FTS5 before "
            "Friday to confirm it holds up under load.",
            [
                ("decision", "use SQLite for the index", {"topic": "storage"}),
                (
                    "task",
                    "Benchmark FTS5 before Friday",
                    {"status": "open", "deadline_text": "before Friday"},
                ),
            ],
        ),
        _example(
            "FTS5 is faster than LIKE queries for our corpus size. Should we "
            "shard the index by year? See https://www.sqlite.org/fts5.html "
            "for the module docs.",
            [
                (
                    "claim",
                    "FTS5 is faster than LIKE queries for our corpus size",
                    None,
                ),
                ("question", "Should we shard the index by year?", None),
                (
                    "reference",
                    "https://www.sqlite.org/fts5.html",
                    {"kind": "url"},
                ),
            ],
        ),
        _example(
            "The team settled on blake3 for content hashing. Someone should "
            "write a migration script by end of quarter. Is blake3 available "
            "on all target platforms? Content hashes are stable across runs "
            "for identical bytes, per the blake3 spec at "
            "https://github.com/BLAKE3-team/BLAKE3.",
            [
                ("decision", "settled on blake3 for content hashing", None),
                (
                    "task",
                    "write a migration script by end of quarter",
                    {"status": "open", "deadline_text": "end of quarter"},
                ),
                (
                    "question",
                    "Is blake3 available on all target platforms?",
                    None,
                ),
                (
                    "claim",
                    "Content hashes are stable across runs for identical bytes",
                    None,
                ),
                (
                    "reference",
                    "https://github.com/BLAKE3-team/BLAKE3",
                    {"kind": "url"},
                ),
            ],
        ),
    ]


def schema_hash() -> str:
    import blake3

    payload = json.dumps(
        {
            "prompt_description": PROMPT_DESCRIPTION,
            "examples": [
                {
                    "text": ex.text,
                    "extractions": [
                        {
                            "extraction_class": e.extraction_class,
                            "extraction_text": e.extraction_text,
                            "attributes": e.attributes,
                        }
                        for e in ex.extractions
                    ],
                }
                for ex in build_examples()
            ],
        },
        sort_keys=True,
    )
    return blake3.blake3(payload.encode("utf-8")).hexdigest()


@dataclass
class RawExtraction:
    extraction_class: str
    extraction_text: str
    char_start: int | None
    char_end: int | None
    alignment_status: str | None
    attributes: dict | None


class Extractor(Protocol):
    def __call__(self, text: str) -> list[RawExtraction]: ...


def make_langextract_extractor(model_id: str, api_key: str | None, **kwargs) -> Extractor:
    """Real backend: calls langextract.extract() against a live model.
    Requires network access and a valid api_key (or provider that doesn't
    need one, e.g. a local Ollama model_id).

    A model_url whose path ends in /v1 is treated as an OpenAI-compatible
    server (LM Studio, vLLM, llama.cpp): the OpenAI provider is selected
    explicitly via ModelConfig, bypassing langextract's model-id pattern
    routing, which would otherwise send local model names (qwen*, gemma*,
    ...) to the Ollama provider."""
    import langextract as lx

    examples = build_examples()

    model_url = kwargs.get("model_url")
    if model_url and model_url.rstrip("/").endswith("/v1"):
        del kwargs["model_url"]
        kwargs["config"] = lx.factory.ModelConfig(
            model_id=model_id,
            provider="OpenAILanguageModel",
            provider_kwargs={
                "base_url": model_url,
                # The provider refuses an empty key; local servers ignore it.
                "api_key": api_key or "unused-local-key",
            },
        )
        api_key = None

    def _extract(text: str) -> list[RawExtraction]:
        result = lx.extract(
            text_or_documents=text,
            prompt_description=PROMPT_DESCRIPTION,
            examples=examples,
            model_id=model_id,
            api_key=api_key,
            show_progress=False,
            **kwargs,
        )
        docs = result if isinstance(result, list) else [result]
        out = []
        for doc in docs:
            for extraction in doc.extractions or []:
                interval = extraction.char_interval
                out.append(
                    RawExtraction(
                        extraction_class=extraction.extraction_class,
                        extraction_text=extraction.extraction_text,
                        char_start=interval.start_pos if interval else None,
                        char_end=interval.end_pos if interval else None,
                        alignment_status=(
                            extraction.alignment_status.value
                            if extraction.alignment_status
                            else None
                        ),
                        attributes=extraction.attributes,
                    )
                )
        return out

    return _extract


def langextract_version() -> str:
    import importlib.metadata

    return importlib.metadata.version("langextract")

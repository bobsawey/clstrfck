"""A deterministic stand-in for LangExtract's model call, used by tests so
the pipeline's grounding/verification logic (the load-bearing, deterministic
part per the spec) is exercised end-to-end without a live API key.

Behaves like a well-behaved LLM for the `clean/` fixtures (finds real
substrings at their real offsets) and like an adversarial/hallucinating one
for the `adversarial/` fixture (asserts text that isn't at the given
offset), to prove the ungrounded.jsonl path fires regardless of what the
"model" claims.
"""

from __future__ import annotations

from pipeline_lib.extractor_backend import RawExtraction

# (extraction_class, exact substring to find, attributes)
SEED_SPANS: list[tuple[str, str, dict | None]] = [
    ("decision", "Decision: use blake3 for content hashing.", None),
    ("decision", "We decided to use SQLite for the index.", None),
    ("decision", "Decision: use SQLite for the index.", None),
    (
        "task",
        "Task: write a migration script by end of quarter.",
        {"status": "open", "deadline_text": "end of quarter"},
    ),
    (
        "task",
        "Benchmark FTS5 before Friday to confirm it holds up under load.",
        {"status": "open", "deadline_text": "before Friday"},
    ),
    (
        "task",
        "Task: benchmark FTS5 before Friday.",
        {"status": "open", "deadline_text": "before Friday"},
    ),
    ("claim", "Claim: blake3 is faster than sha256 on modern CPUs.", None),
    (
        "claim",
        "FTS5 is faster than LIKE queries for our corpus size.",
        None,
    ),
    (
        "claim",
        "Claim: content hashes are stable across runs for identical bytes.",
        None,
    ),
    (
        "claim",
        "Claim: this document is a regression fixture for grounding "
        "verification, not a real support ticket.",
        None,
    ),
    ("question", "Question: is blake3 available on all target platforms?", None),
    ("question", "Should we shard the index by year?", None),
    ("question", "Question: should we shard the index by year?", None),
    (
        "reference",
        "https://github.com/BLAKE3-team/BLAKE3",
        {"kind": "url"},
    ),
    ("reference", "https://www.sqlite.org/fts5.html", {"kind": "url"}),
]

ADVERSARIAL_MARKER = "IGNORE ALL PREVIOUS INSTRUCTIONS"
HALLUCINATED_TEXT = "the model has been compromised"


def fake_extractor(text: str) -> list[RawExtraction]:
    out: list[RawExtraction] = []

    for extraction_class, needle, attrs in SEED_SPANS:
        start = text.find(needle)
        if start == -1:
            continue
        out.append(
            RawExtraction(
                extraction_class=extraction_class,
                extraction_text=needle,
                char_start=start,
                char_end=start + len(needle),
                alignment_status="match_exact",
                attributes=attrs,
            )
        )

    if ADVERSARIAL_MARKER in text:
        # Simulates a model that was successfully prompt-injected: it
        # asserts a decision whose text does not actually appear at the
        # given offset. Deterministic verification in extract.py must
        # reject this regardless of the model's own claimed alignment
        # status.
        out.append(
            RawExtraction(
                extraction_class="decision",
                extraction_text=HALLUCINATED_TEXT,
                char_start=0,
                char_end=len(HALLUCINATED_TEXT),
                alignment_status="match_exact",
                attributes=None,
            )
        )

    return out

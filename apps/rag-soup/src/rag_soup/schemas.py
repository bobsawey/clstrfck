from dataclasses import dataclass, field
from typing import List, Dict, Tuple


@dataclass
class DocMeta:
    doc_uid: str
    source_uid: str
    path: str
    mime: str
    bytes: int
    checksum: str
    created_ts: str
    modified_ts: str
    author: str | None
    title: str | None
    license: str | None
    consent_flags: List[str] = field(default_factory=list)
    retention_class: str = "unknown"
    risk_tags: List[str] = field(default_factory=list)
    nsfw_score: float = 0.0
    toxicity_score: float = 0.0
    illicit_score: float = 0.0
    pii_score: float = 0.0
    domain_tags: List[str] = field(default_factory=list)
    topic_labels: List[str] = field(default_factory=list)
    lang: str = "und"
    charset: str = "utf-8"
    chunk_count: int = 0
    quarantine: bool = False


@dataclass
class Chunk:
    doc_uid: str
    chunk_id: str
    text: str
    offset: Tuple[int, int]
    lang: str
    labels: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)

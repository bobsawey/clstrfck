import argparse, hashlib, mimetypes, os, shutil, time, re, json, unicodedata
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple
import chardet
import pandas as pd

ZONE_CFG = {
    "thresholds": {"nsfw": 0.55, "toxicity": 0.50, "illicit": 0.35, "pii": 0.60},
    "chunk_tokens_min": 120,
    "chunk_tokens_max": 900,
}


def _tokens(s: str) -> int:
    return max(1, len(s.split()))


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def norm_text(txt: str) -> str:
    txt = unicodedata.normalize("NFC", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def detect_encoding(path: Path) -> str:
    with open(path, "rb") as f:
        raw = f.read(100_000)
    guess = chardet.detect(raw)
    return guess.get("encoding") or "utf-8"


def read_text_like(path: Path) -> str | None:
    mime, _ = mimetypes.guess_type(str(path))
    ext = (path.suffix or "").lower()
    try:
        enc = detect_encoding(path)
        text = path.read_text(encoding=enc, errors="ignore")
        if ext in {".html", ".htm"}:
            text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
            text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
        return norm_text(text)
    except Exception:
        return None


def chunk_paragraphs(
    text: str, tmin=ZONE_CFG["chunk_tokens_min"], tmax=ZONE_CFG["chunk_tokens_max"]
):
    paras = re.split(r"\n\s*\n", text)
    chunks, buf, start_off = [], [], 0
    cur_tokens = 0
    for p in paras:
        if not p.strip():
            start_off += len(p) + 2
            continue
        t = _tokens(p)
        if cur_tokens + t <= tmax:
            buf.append(p)
            cur_tokens += t
        else:
            if cur_tokens >= tmin:
                chunk_text = "\n\n".join(buf).strip()
                end_off = start_off + len(chunk_text)
                chunks.append((start_off, end_off, chunk_text))
                start_off += len(chunk_text) + 2
                buf, cur_tokens = [p], t
            else:
                buf.append(p)
                chunk_text = "\n\n".join(buf).strip()
                end_off = start_off + len(chunk_text)
                chunks.append((start_off, end_off, chunk_text))
                start_off += len(chunk_text) + 2
                buf, cur_tokens = [], 0
    if buf:
        chunk_text = "\n\n".join(buf).strip()
        end_off = start_off + len(chunk_text)
        chunks.append((start_off, end_off, chunk_text))
    return chunks


# naive regex heuristics (swap with ML classifiers later)
NSFW_PAT = re.compile(r"\b(nude|porn|xxx|explicit|nsfw|sexual|fetish)\b", re.I)
TOX_PAT = re.compile(r"\b(idiot|stupid|hate|kill|slur)\b", re.I)
ILL_PAT = re.compile(r"\b(how to make a bomb|credit card dump|exploit kit|c2 server)\b", re.I)
PII_PAT = re.compile(r"\b(\d{3}-\d{2}-\d{4})\b")


def safety_scores(text: str) -> Dict[str, float]:
    nsfw = 1.0 if NSFW_PAT.search(text) else 0.0
    tox = 1.0 if TOX_PAT.search(text) else 0.0
    ill = 1.0 if ILL_PAT.search(text) else 0.0
    pii = 1.0 if PII_PAT.search(text) else 0.0
    return {"nsfw": nsfw, "toxicity": tox, "illicit": ill, "pii": pii, "conf": 0.5}


def decide_zone(doc_scores: Dict[str, float], thresholds=ZONE_CFG["thresholds"]):
    reasons = [k for k, v in doc_scores.items() if k in thresholds and v >= thresholds[k]]
    zone = "red_quarantine" if reasons else "silver_normalized"
    return zone, reasons


@dataclass
class DocRow:
    doc_uid: str
    dataset_id: str
    source_path: str
    mime: str
    bytes: int
    checksum: str
    created_ts: str
    modified_ts: str
    title: str | None
    author: str | None
    lang: str
    charset: str
    chunk_count: int
    quarantine: bool
    nsfw_score: float
    toxicity_score: float
    illicit_score: float
    pii_score: float
    risk_tags: List[str]


@dataclass
class ChunkRow:
    doc_uid: str
    chunk_id: str
    idx: int
    offset_start: int
    offset_end: int
    lang: str
    nsfw_score: float
    toxicity_score: float
    illicit_score: float
    pii_score: float
    text: str


def mine_dataset(input_dir: Path, root: Path, dataset_id: str):
    bronze = root / "bronze_raw"
    silver = root / "silver_normalized"
    red = root / "red_quarantine"
    catalog = root / "catalog"
    for p in (bronze, silver, red, catalog, catalog / "dataset_cards"):
        p.mkdir(parents=True, exist_ok=True)

    docs_rows: List[DocRow] = []
    chunks_rows: List[ChunkRow] = []

    all_files = [p for p in Path(input_dir).rglob("*") if p.is_file()]
    for path in all_files:
        try:
            raw = path.read_bytes()
        except Exception:
            continue
        checksum = sha256_hex(raw)
        size = len(raw)
        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "application/octet-stream"

        bronze_path = bronze / checksum[:2] / checksum
        bronze_path.parent.mkdir(parents=True, exist_ok=True)
        if not bronze_path.exists():
            shutil.copy2(path, bronze_path)

        text = read_text_like(path)
        if not text:
            zone_name = "red_quarantine"
            reasons = ["non_text"]
            doc_scores = {"nsfw": 0, "toxicity": 0, "illicit": 0, "pii": 0}
            chunks = []
        else:
            chunks = chunk_paragraphs(text)
            agg = {"nsfw": 0.0, "toxicity": 0.0, "illicit": 0.0, "pii": 0.0}
            for s, e, txt in chunks:
                sc = safety_scores(txt)
                for k in agg:
                    agg[k] = max(agg[k], sc[k])
            zone_name, reasons = decide_zone(agg)
            doc_scores = agg

        zone = silver if zone_name == "silver_normalized" else red
        norm_dir = zone / "docs" / checksum[:2]
        norm_dir.mkdir(parents=True, exist_ok=True)
        if text:
            (norm_dir / f"{checksum}.txt").write_text(text, encoding="utf-8")

        stat = path.stat()
        doc = DocRow(
            doc_uid=checksum[:24],
            dataset_id=dataset_id,
            source_path=str(path),
            mime=mime,
            bytes=size,
            checksum=checksum,
            created_ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_ctime)),
            modified_ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
            title=path.name,
            author=None,
            lang="und",
            charset="utf-8",
            chunk_count=len(chunks),
            quarantine=(zone_name == "red_quarantine"),
            nsfw_score=doc_scores["nsfw"],
            toxicity_score=doc_scores["toxicity"],
            illicit_score=doc_scores["illicit"],
            pii_score=doc_scores["pii"],
            risk_tags=reasons,
        )
        docs_rows.append(doc)

        if text and chunks:
            chunk_dir = zone / "chunks" / checksum[:2]
            chunk_dir.mkdir(parents=True, exist_ok=True)
            for idx, (s, e, txt) in enumerate(chunks):
                chunk_id = f"{checksum[:24]}:{idx}"
                (chunk_dir / f"{chunk_id}.txt").write_text(txt, encoding="utf-8")
                sc = safety_scores(txt)
                chunks_rows.append(
                    ChunkRow(
                        doc_uid=checksum[:24],
                        chunk_id=chunk_id,
                        idx=idx,
                        offset_start=s,
                        offset_end=e,
                        lang="und",
                        nsfw_score=sc["nsfw"],
                        toxicity_score=sc["toxicity"],
                        illicit_score=sc["illicit"],
                        pii_score=sc["pii"],
                        text=txt,
                    )
                )

    docs_df = pd.DataFrame([asdict(r) for r in docs_rows])
    chunks_df = pd.DataFrame([asdict(r) for r in chunks_rows])
    (catalog / "docs.parquet").unlink(missing_ok=True)
    (catalog / "chunks.parquet").unlink(missing_ok=True)
    docs_df.to_parquet(catalog / "docs.parquet", index=False)
    chunks_df.to_parquet(catalog / "chunks.parquet", index=False)

    card = {
        "id": dataset_id,
        "source": str(input_dir),
        "scope": "personal+work_mixed",
        "license_summary": "mixed/unknown (default restricted)",
        "pii": "present-high" if (docs_df.pii_score > 0).any() else "unknown",
        "nsfw": "present" if (docs_df.nsfw_score > 0).any() else "unknown",
        "toxic": "present" if (docs_df.toxicity_score > 0).any() else "unknown",
        "provenance_notes": "auto-mined; manual review advised",
        "routing": {
            "quarantine_docs": int(docs_df.quarantine.sum()),
            "clean_docs": int((~docs_df.quarantine).sum()),
        },
        "retention": {
            "review_by": time.strftime("%Y-%m-%d", time.gmtime(time.time() + 365 * 24 * 3600))
        },
        "intended_use": ["discovery", "filter_training", "research"],
    }
    (catalog / "dataset_cards" / f"{dataset_id}.yaml").write_text(json.dumps(card, indent=2))
    print(f"Mining complete. Docs: {len(docs_rows)} | Chunks: {len(chunks_rows)}")
    print(
        f"Quarantined: {int(docs_df.quarantine.sum())} | Clean: {int((~docs_df.quarantine).sum())}"
    )
    print(f"Catalog: {catalog/'docs.parquet'}  {catalog/'chunks.parquet'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="directory to mine (recursively)")
    ap.add_argument("--root", required=True, help="data root (contains bronze/…/catalog)")
    ap.add_argument("--dataset-id", required=True, help="id for dataset card + catalog")
    args = ap.parse_args()
    mine_dataset(Path(args.input), Path(args.root), args.dataset_id)


if __name__ == "__main__":
    main()

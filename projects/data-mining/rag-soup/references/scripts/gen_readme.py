import yaml, pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CATALOG = ROOT / "resources.yaml"
README = ROOT / "README.md"

GROUPS = [
    ("Retrieval — sparse/dense/late", ["retrieval", "sparse", "dense", "late-interaction"]),
    ("Reranking", ["reranking"]),
    ("Fusion — RRF & score fusion", ["fusion"]),
    ("Expansion — RF/PRF/doc2query", ["expansion"]),
    ("Diversification — MMR", ["diversification"]),
    ("Evaluation — BEIR/MS MARCO", ["evaluation"]),
    ("Agentic RAG", ["agentic-rag"]),
    ("Foundations — textbooks/surveys", ["foundations"]),
    ("Production — Azure/hosted rerankers", ["production"]),
    ("Security — prompt/context injection", ["security"]),
]


def load_items():
    data = yaml.safe_load(CATALOG.read_text())
    return data.get("items", [])


def md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def section(title, items):
    if not items:
        return f"## {title}\n\n_(no entries yet)_\n"
    head = f"## {title}\n\n| ID | Title | Year | Type | Link |\n|---|---|---:|---|---|\n"
    rows = []
    for it in items:
        url = it.get("url", "")
        link = f"[link]({url})" if url else ""
        rows.append(
            f"| {md_escape(it['id'])} | {md_escape(it['title'])} | {it.get('year','')} | {it.get('type','')} | {link} |"
        )
    return head + "\n".join(rows) + "\n"


def main():
    items = load_items()
    parts = [
        "# RAG / IR / NLP References\n\n> Auto-generated from `resources.yaml`. Edit YAML, then run `python scripts/gen_readme.py`.\n"
    ]
    for title, tags in GROUPS:
        group_items = []
        for t in tags:
            group_items.extend([i for i in items if t in i.get("tags", [])])
        seen = set()
        uniq = []
        for it in group_items:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            uniq.append(it)
        parts.append(section(title, uniq))
    README.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {README}")


if __name__ == "__main__":
    main()

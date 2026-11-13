# clstrfck

This project is pivoting toward an ambitious attempt to build personal knowledge graphing and data tracking and provenance solutions I've been dreaming up for some time. Still quite a bit to document about this and will continue to update this README accordingly.

__*This repo is changing swiftly now that I've finallly had some time to begin cleaning and organizing and further aiming toward the emerging goals of creating a personal document and knowledge graph type thing that can do really neat stuff and doesn't harshly rely on LLM's for everything and with an interface in the future that we hope will be nice and of great utility.*__


## Highlight: extraction-pipeline

The most active and functional project here is
[`apps/extraction-pipeline`](apps/extraction-pipeline/) — a
provenance-preserving pipeline that snapshots a source tree, indexes it
deterministically, normalizes documents to text/Markdown, and uses an LLM
(via LangExtract, against local or hosted models) to extract semantic
artifacts grounded to exact character spans in the source. Fully tested,
resumable, all state in SQLite. Start with its
[README](apps/extraction-pipeline/README.md).

It supersedes the earlier mining-pipeline stubs in `apps/miner` and the
design sketches in `docs/mining-prep.md` / `docs/architecture.md`, which are
kept as reference.

## Layout

- `apps/` – runnable command line tools
  - `extraction-pipeline/` – provenance-preserving document extraction (see above)
  - `miner/` – earlier mining pipeline stubs (superseded, kept for reference)
  - `rag-soup/`, `rlhf-maker/`, `chat-conversation-viewer/`, `repo-sweep/`,
    `xcode-cli-tools-installer/` – smaller tools and experiments
- `libs/` – reusable libraries (`clusterkit`, `atzmo`)
- `experiments/` – throwaway notebooks and spikes
- `docs/` – reference material and architecture notes
- `tests/` – mirrors `apps/` and `libs/` package structure
  (extraction-pipeline keeps its own `tests/` inside its directory)
- `data/` – placeholder for raw and processed datasets (ignored)


*again, there is a lot changing with the repo at the moment. things will hopefully be more grounded soon ;)*

<del>pip install -e libs/clusterkit</del>
<del>pip install -e libs/atzmo</del>
<del>pip install -e apps/rag-soup</del>


Run tests with:

```sh
pytest -q
```

For the extraction pipeline, see
[apps/extraction-pipeline/DEVELOPING.md](apps/extraction-pipeline/DEVELOPING.md).

## License

Apache 2.0 – see [LICENSE](LICENSE).

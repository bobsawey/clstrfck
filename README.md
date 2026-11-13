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

## Exploration: hi-fi functional mockup
https://clstrfckstudiomock.vercel.app/

A throwaway prototype I directed coding agents to build quickly, to test the interaction model before committing to a real front end. It's deliberately not the final direction. What it taught me:
- [lesson 1, e.g. what felt wrong about the layout or flow]
- [lesson 2]
- [what the real front end will do differently]

The information architecture is going to be a real beast to chunk through so I needed help by making pretty stuff that is responsive that in some ways tries to resemble the sorts of things I want to do but totally is way off in a lot of ways.

You know... Robust, but not completely with it: something hours of vibe coding can always bring. That way we can actually take an architectural / system thinking approach here and actually write specs to follow based on carefully diagrammed and deeply considered stuff. I'll try to provide examples IA guidance that meets my standards and approaches to better reflect the level of quality I hope to have in the design documents for this at some point.

note: many things below this line are going to be out of date in some way but I'm incrementing here and it will stay until I've cleared things up.

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

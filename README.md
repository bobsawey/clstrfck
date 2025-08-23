# clstrfck

A public scratch space for data mining and automation experiments.

## Layout

- `apps/` – runnable command line tools
- `libs/` – reusable libraries
- `experiments/` – throwaway notebooks and spikes
- `docs/` – reference material and architecture notes (see [docs/mining-prep.md](docs/mining-prep.md) for the mining pipeline)
- `tests/` – mirrors `apps/` and `libs/` package structure
- `data/` – placeholder for raw and processed datasets (ignored)

## Getting Started

```sh
pip install -e libs/clusterkit
pip install -e libs/atzmo
pip install -e apps/rag-soup
```

Run tests with:

```sh
pytest -q
```

## License

Apache 2.0 – see [LICENSE](LICENSE).

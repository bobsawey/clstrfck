setup:
	python -m venv .venv && . .venv/bin/activate && pip install -e apps/rag-soup -e libs/clusterkit -e libs/atzmo -r requirements-dev.txt

test:
	pytest -q

lint:
	ruff check .

fmt:
	black .

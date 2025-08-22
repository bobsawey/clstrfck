import yaml, re, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / "resources.yaml"


def test_schema_and_links():
    data = yaml.safe_load(CATALOG.read_text())
    assert "items" in data and isinstance(data["items"], list)
    ids = set()
    for it in data["items"]:
        for key in ["id", "title", "year", "type", "tags"]:
            assert key in it
        assert it["id"] not in ids
        ids.add(it["id"])
        if it.get("url"):
            assert re.match(r"https?://", it["url"])

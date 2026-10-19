"""Tests for the derived catalog (pipeline_lib/catalog.py).

catalog.sqlite is a second, disposable database derived from index.sqlite
+ the JSONLs: a wide denormalized artifact table whose schema grows a
column the first time a new model-emitted attribute key appears, plus
auto/manual tagging. The things worth pinning down: upserts are
idempotent, schema evolution is add-only and audited, rebuild pares
columns back down, and manual tags survive both sync and rebuild.
"""

from __future__ import annotations

import json

import pytest

from pipeline_lib import catalog, db
from pipeline_lib.paths import WorkPaths

from tests.fake_extractor import HALLUCINATED_TEXT
from tests.test_pipeline import _run_extract, _snapshot_index_normalize


@pytest.fixture
def work(tmp_path) -> WorkPaths:
    return WorkPaths(tmp_path / "work")


@pytest.fixture
def extracted(work):
    """Full pipeline through extract (fake model), plus open connections."""
    conn, _, _ = _snapshot_index_normalize(work)
    _run_extract(conn, work)
    cat = catalog.connect(work.catalog_sqlite)
    return conn, cat, work


def test_sync_builds_wide_rows_with_provenance_and_attr_columns(extracted):
    conn, cat, work = extracted
    stats = catalog.sync(conn, cat, work)

    n_artifacts = conn.execute("SELECT COUNT(*) AS n FROM artifact").fetchone()["n"]
    assert stats.grounded_rows == n_artifacts
    assert stats.ungrounded_rows >= 1

    # Attribute keys from the fixtures became real columns.
    cols = catalog.table_columns(cat, "artifact_wide")
    assert "attr_status" in cols
    assert "attr_deadline_text" in cols
    assert "attr_kind" in cols

    row = cat.execute(
        "SELECT * FROM artifact_wide WHERE attr_deadline_text = 'end of quarter' "
        "AND source_path = 'clean/notes.txt'"
    ).fetchone()
    assert row is not None
    assert row["grounded"] == 1
    assert row["attr_status"] == "open"
    assert row["extraction_class"] == "task"
    assert row["source_mime"] == "text/plain"
    assert row["model_id"] == "test-fake-model"
    assert row["rep_kind"] == "text_utf8"
    # Context snippets really surround the span in the normalized text.
    text = (work.root / row["rep_path"]).read_text(encoding="utf-8")
    assert text[row["char_start"]:row["char_end"]] == row["extraction_text"]
    assert row["context_before"] == text[:row["char_start"]][-catalog.CONTEXT_CHARS:]
    assert text[row["char_end"]:].startswith(row["context_after"])


def test_ungrounded_rows_are_included_but_marked(extracted):
    conn, cat, work = extracted
    catalog.sync(conn, cat, work)

    row = cat.execute(
        "SELECT * FROM artifact_wide WHERE extraction_text = ?",
        (HALLUCINATED_TEXT,),
    ).fetchone()
    assert row is not None
    assert row["grounded"] == 0
    assert row["rejection_reason"]
    assert row["context_before"] is None  # unverified span: never quoted around
    tags = json.loads(row["tags"])
    assert "ungrounded" in tags
    assert "class:decision" in tags


def test_sync_is_idempotent_upsert(extracted):
    conn, cat, work = extracted
    stats1 = catalog.sync(conn, cat, work)
    n1 = cat.execute("SELECT COUNT(*) AS n FROM artifact_wide").fetchone()["n"]
    log1 = cat.execute("SELECT COUNT(*) AS n FROM schema_log").fetchone()["n"]

    stats2 = catalog.sync(conn, cat, work)
    n2 = cat.execute("SELECT COUNT(*) AS n FROM artifact_wide").fetchone()["n"]
    log2 = cat.execute("SELECT COUNT(*) AS n FROM schema_log").fetchone()["n"]

    assert n2 == n1
    assert stats2.columns_added == []
    assert log2 == log1  # no new schema changes on a no-op sync
    assert stats2.auto_tags == 0  # tags already present

    # first_synced_at is preserved; synced_at moves forward or stays equal.
    row = cat.execute("SELECT first_synced_at, synced_at FROM artifact_wide LIMIT 1").fetchone()
    assert row["first_synced_at"] <= row["synced_at"]


def test_schema_evolves_when_new_attribute_key_appears(extracted):
    conn, cat, work = extracted
    catalog.sync(conn, cat, work)
    assert "attr_severity" not in catalog.table_columns(cat, "artifact_wide")

    # Simulate a later extraction run whose model emitted a never-seen
    # attribute key (numeric, to check type mapping too).
    art = conn.execute("SELECT * FROM artifact LIMIT 1").fetchone()
    conn.execute(
        "UPDATE artifact SET attributes_json = ? WHERE artifact_id = ?",
        (json.dumps({"severity": "high", "confidence_rank": 3}), art["artifact_id"]),
    )
    conn.commit()

    stats = catalog.sync(conn, cat, work)
    assert "attr_severity" in stats.columns_added
    assert "attr_confidence_rank" in stats.columns_added

    row = cat.execute(
        "SELECT * FROM artifact_wide WHERE artifact_id = ?", (art["artifact_id"],),
    ).fetchone()
    assert row["attr_severity"] == "high"
    assert row["attr_confidence_rank"] == 3

    # Every addition is audited.
    logged = {
        r["column_name"] for r in cat.execute(
            "SELECT column_name FROM schema_log WHERE reason LIKE 'attribute key%'"
        )
    }
    assert {"attr_severity", "attr_confidence_rank"} <= logged
    # The new value also became an auto tag.
    assert "severity:high" in json.loads(row["tags"])


def test_manual_tags_survive_sync_and_rebuild(extracted):
    conn, cat, work = extracted
    catalog.sync(conn, cat, work)

    art_id = cat.execute(
        "SELECT artifact_id FROM artifact_wide WHERE grounded = 1 LIMIT 1"
    ).fetchone()["artifact_id"]
    catalog.add_manual_tag(cat, art_id, "important")
    catalog.add_manual_tag(cat, art_id[:10], "review-later")  # prefix works too

    catalog.sync(conn, cat, work)
    tags_after_sync = json.loads(cat.execute(
        "SELECT tags FROM artifact_wide WHERE artifact_id = ?", (art_id,),
    ).fetchone()["tags"])
    assert "important" in tags_after_sync and "review-later" in tags_after_sync

    catalog.sync(conn, cat, work, rebuild=True)
    row = cat.execute(
        "SELECT tags FROM artifact_wide WHERE artifact_id = ?", (art_id,),
    ).fetchone()
    assert "important" in json.loads(row["tags"])

    catalog.remove_tag(cat, art_id, "important")
    assert "important" not in json.loads(cat.execute(
        "SELECT tags FROM artifact_wide WHERE artifact_id = ?", (art_id,),
    ).fetchone()["tags"])


def test_rebuild_pares_stale_columns_back_down(extracted):
    conn, cat, work = extracted
    catalog.sync(conn, cat, work)

    # A column nobody's data needs anymore (e.g. from an abandoned prompt
    # iteration) lingers after normal syncs...
    catalog.ensure_columns(
        cat, "artifact_wide", {"attr_abandoned_experiment": "TEXT"}, reason="test",
    )
    cat.commit()
    assert "attr_abandoned_experiment" in catalog.table_columns(cat, "artifact_wide")
    catalog.sync(conn, cat, work)
    assert "attr_abandoned_experiment" in catalog.table_columns(cat, "artifact_wide")

    # ...and rebuild drops it while keeping all rows.
    n_before = cat.execute("SELECT COUNT(*) AS n FROM artifact_wide").fetchone()["n"]
    catalog.sync(conn, cat, work, rebuild=True)
    assert "attr_abandoned_experiment" not in catalog.table_columns(cat, "artifact_wide")
    n_after = cat.execute("SELECT COUNT(*) AS n FROM artifact_wide").fetchone()["n"]
    assert n_after == n_before


def test_resolve_artifact_prefix_rejects_ambiguous_and_missing(extracted):
    conn, cat, work = extracted
    catalog.sync(conn, cat, work)

    with pytest.raises(ValueError, match="no artifact matches"):
        catalog.resolve_artifact(cat, "zzzzzz")
    # 'art_' alone matches every row -> ambiguous.
    with pytest.raises(ValueError, match="ambiguous"):
        catalog.resolve_artifact(cat, "art_")


def test_cli_catalog_and_tag_commands(extracted, capsys):
    conn, cat, work = extracted
    del conn, cat  # CLI opens its own connections

    import pipeline

    assert pipeline.main(["--work-dir", str(work.root), "catalog"]) == 0
    out = capsys.readouterr().out
    assert "catalog summary" in out
    assert "grounded rows" in out

    fresh = catalog.connect(work.catalog_sqlite)
    art_id = fresh.execute(
        "SELECT artifact_id FROM artifact_wide LIMIT 1"
    ).fetchone()["artifact_id"]

    assert pipeline.main(
        ["--work-dir", str(work.root), "tag", art_id, "--add", "starred"]
    ) == 0
    out = capsys.readouterr().out
    assert "starred" in out

    assert pipeline.main(["--work-dir", str(work.root), "tag"]) == 0
    out = capsys.readouterr().out
    assert "starred" in out  # shows up in the vocabulary listing

    assert pipeline.main(
        ["--work-dir", str(work.root), "tag", "no_such_artifact", "--add", "x"]
    ) == 1

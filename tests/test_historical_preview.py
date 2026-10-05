from contextlib import closing
import json
import sqlite3

import pytest

from scripts import run_historical_preview as preview


def test_preview_backup_keeps_source_and_independent_record_identity(tmp_path, monkeypatch):
    current = tmp_path / "current"
    historical = tmp_path / "historical"
    source = current / "data" / "phones.sqlite3"
    source.parent.mkdir(parents=True)
    record = json.dumps({"id": "specific-512", "storage_gb": 512, "ram_gb": None, "price": 7499,
        "field_sources": {"price": {"source_url": "https://example.com/512", "fetched_at": "2026-10-05"}}})
    with closing(sqlite3.connect(source)) as database:
        database.executescript("CREATE TABLE phones(id TEXT, record_json TEXT); CREATE TABLE raw_snapshots(id INTEGER); CREATE TABLE image_overrides(id TEXT);")
        database.execute("INSERT INTO phones VALUES (?, ?)", ("specific-512", record))
        database.execute("INSERT INTO raw_snapshots VALUES (1)")
        database.execute("INSERT INTO image_overrides VALUES ('specific-512')")
        database.commit()
    original_bytes = source.read_bytes()
    monkeypatch.setattr(preview, "PROJECT_ROOT", current)
    monkeypatch.setattr(preview, "PREVIEW_ROOT", historical)

    preview.copy_current_data()

    assert source.read_bytes() == original_bytes
    with closing(sqlite3.connect(historical / "data" / "phones.sqlite3")) as database:
        assert database.execute("SELECT id, record_json FROM phones").fetchone() == ("specific-512", record)
        database.execute("DELETE FROM phones")
        database.commit()
    assert source.read_bytes() == original_bytes


def test_wrong_historical_checkout_is_rejected_before_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(preview, "PREVIEW_ROOT", tmp_path)
    revisions = iter(["different-commit", "expected-commit"])
    monkeypatch.setattr(preview.subprocess, "check_output", lambda *args, **kwargs: next(revisions))
    commands = []
    monkeypatch.setattr(preview.subprocess, "run", lambda *args, **kwargs: commands.append(args))

    with pytest.raises(ValueError, match="不是指定的"):
        preview.prepare_preview()

    assert commands == []

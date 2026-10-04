import gzip
import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from scripts.restore_snapshot import restore_snapshot


def test_restore_snapshot_preserves_database_bytes(tmp_path):
    original = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(original)) as database:
        database.execute("CREATE TABLE phones (name TEXT)")
        database.execute("INSERT INTO phones VALUES ('保留原配置')")
        database.commit()
    snapshot_dir = tmp_path / "project" / "data" / "snapshots"
    snapshot_dir.mkdir(parents=True)
    compressed = gzip.compress(original.read_bytes())
    (snapshot_dir / "phones.sqlite3.gz").write_bytes(compressed)
    (snapshot_dir / "manifest.json").write_text(json.dumps({
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "database_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "database_bytes": original.stat().st_size,
        "phone_count": 1, "raw_snapshot_count": 0,
    }), encoding="utf-8")

    restore_snapshot(tmp_path / "project")

    restored = tmp_path / "project" / "data" / "phones.sqlite3"
    assert restored.read_bytes() == original.read_bytes()
    with closing(sqlite3.connect(restored)) as database:
        assert database.execute("SELECT name FROM phones").fetchone()[0] == "保留原配置"


def test_restore_keeps_existing_database_without_needing_snapshot(tmp_path):
    database = tmp_path / "data" / "phones.sqlite3"
    database.parent.mkdir()
    database.write_bytes(b"existing database")

    restore_snapshot(tmp_path)

    assert database.read_bytes() == b"existing database"


def test_invalid_snapshot_hash_does_not_create_database(tmp_path):
    snapshot_dir = tmp_path / "data" / "snapshots"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "phones.sqlite3.gz").write_bytes(gzip.compress(b"changed snapshot"))
    (snapshot_dir / "manifest.json").write_text(json.dumps({"compressed_sha256": "0" * 64}), encoding="utf-8")

    with pytest.raises(ValueError, match="快照校验失败"):
        restore_snapshot(tmp_path)

    assert not (tmp_path / "data" / "phones.sqlite3").exists()


def test_invalid_gzip_does_not_leave_partial_database(tmp_path):
    snapshot_dir = tmp_path / "data" / "snapshots"
    snapshot_dir.mkdir(parents=True)
    compressed = b"not a gzip archive"
    (snapshot_dir / "phones.sqlite3.gz").write_bytes(compressed)
    (snapshot_dir / "manifest.json").write_text(json.dumps({
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
    }), encoding="utf-8")

    with pytest.raises(gzip.BadGzipFile):
        restore_snapshot(tmp_path)

    assert not (tmp_path / "data" / "phones.sqlite3").exists()


def test_decompressed_checksum_mismatch_removes_own_database(tmp_path):
    snapshot_dir = tmp_path / "data" / "snapshots"
    snapshot_dir.mkdir(parents=True)
    compressed = gzip.compress(b"unexpected database")
    (snapshot_dir / "phones.sqlite3.gz").write_bytes(compressed)
    (snapshot_dir / "manifest.json").write_text(json.dumps({
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "database_bytes": len(b"unexpected database"),
        "database_sha256": "0" * 64,
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="数据库校验失败"):
        restore_snapshot(tmp_path)

    assert not (tmp_path / "data" / "phones.sqlite3").exists()

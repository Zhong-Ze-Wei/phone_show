from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import sqlite3
from unittest.mock import Mock

from fastapi.testclient import TestClient
from phone_assistant.config import Settings
from phone_assistant.response_cache import CatalogueResponseCache, CatalogueSnapshot
from phone_assistant.server import create_app
from phone_assistant.storage import Storage


def test_response_cache_expiry_revision_and_bounds():
    version, now = [1], [0]
    cache = CatalogueResponseCache(lambda: version[0], ttl=60, max_bytes=40, max_entries=2, clock=lambda: now[0])
    build = Mock(return_value={'price': 99})
    assert cache.response('a', build).headers['x-catalogue-cache'] == 'MISS'
    assert cache.response('a', build).headers['x-catalogue-cache'] == 'HIT'
    now[0] = 60
    cache.response('a', build)
    assert build.call_count == 2
    version[0] += 1
    cache.response('a', build)
    assert build.call_count == 3
    cache.response('b', build)
    cache.response('c', build)
    assert len(cache.entries) == 2 and cache.size <= 40
    assert 'a' not in cache.entries
    cache.response('huge', lambda: {'text': 'x' * 100})
    assert 'huge' not in cache.entries


def test_concurrent_cold_requests_build_once():
    cache = CatalogueResponseCache(lambda: 1)
    build = Mock(return_value={'price': 123})
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: cache.response('same', build).body, range(6)))
    assert len(set(results)) == 1
    build.assert_called_once()


def test_external_wal_write_invalidates_snapshot_and_response(tmp_path):
    storage = Storage(tmp_path / 'phones.db')
    storage.upsert_raw({'id': 'one', 'name': '小米 15', 'brand': '小米', 'price': 4999,
        'origin': 'zol', 'availability': 'listed', 'fetched_at': datetime.now(timezone.utc).isoformat(),
        'source_url': 'https://example.com/one', 'specs': {'RAM容量': '12GB', 'ROM容量': '256GB'}})
    app = create_app(storage, Settings('test'))
    client = TestClient(app)
    first = client.post('/api/filter', json={})
    assert first.status_code == 200
    assert first.json()['phones'][0]['price'] == 4999
    assert client.post('/api/filter', json={}).headers['x-catalogue-cache'] == 'HIT'
    # Keep the external WAL connection open: invalidation must not rely on DB mtime alone.
    with sqlite3.connect(storage.path) as other:
        other.execute('PRAGMA journal_mode=WAL')
        record = json.loads(other.execute('SELECT record_json FROM phones WHERE id=?', ('one',)).fetchone()[0])
        record['price'] = 3999
        other.execute('UPDATE phones SET record_json=? WHERE id=?', (json.dumps(record), 'one'))
        other.commit()
        fresh = client.post('/api/filter', json={})
        assert fresh.headers['x-catalogue-cache'] == 'MISS'
        assert fresh.json()['phones'][0]['price'] == 3999
    before = storage.list_phones()
    client.post('/api/filter', json={'budget_max': 3000})
    client.post('/api/filter', json={'query': '小米'})
    assert storage.list_phones() == before


def test_snapshot_reuses_read_but_reloads_after_change():
    storage = Mock()
    storage.revision.return_value = 1
    storage.list_phones.return_value = [{'id': 'one'}]
    snapshot = CatalogueSnapshot(storage)
    assert snapshot.read() == snapshot.read()
    storage.list_phones.assert_called_once()
    storage.revision.return_value = 2
    snapshot.read()
    assert storage.list_phones.call_count == 2

def test_filter_does_not_mutate_shared_snapshot(tmp_path):
    from copy import deepcopy
    from phone_assistant.recommendation import filter_phones, Preferences
    storage = Storage(tmp_path / 'phones.db')
    storage.upsert_raw({'id': 'one', 'name': '小米 15', 'brand': '小米', 'price': 4999,
        'origin': 'zol', 'availability': 'listed', 'fetched_at': datetime.now(timezone.utc).isoformat(),
        'source_url': 'https://example.com/one', 'specs': {'RAM容量': '12GB', 'ROM容量': '256GB'}})
    snapshot = CatalogueSnapshot(storage)
    original = deepcopy(snapshot.read())
    filter_phones(snapshot.read(), Preferences())
    filter_phones(snapshot.read(), Preferences(budget_max=3000, query='小米'))
    assert snapshot.read() == original

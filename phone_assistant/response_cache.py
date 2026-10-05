"""Bounded cache of public catalogue JSON, invalidated by database changes."""

from collections import OrderedDict
import json
from threading import Lock
from time import monotonic

from fastapi.responses import Response


class CatalogueSnapshot:
    """Share one read-only enriched catalogue between filter requests."""
    def __init__(self, storage):
        self.storage = storage
        self.version = None
        self.phones = None
        self.lock = Lock()

    def read(self):
        with self.lock:
            version = self.storage.revision()
            if self.phones is not None and version == self.version:
                return self.phones
            phones = self.storage.list_phones()
            if self.storage.revision() == version:
                self.phones, self.version = phones, version
            return phones


class CatalogueResponseCache:
    def __init__(self, revision, *, ttl=60, max_bytes=32 * 1024 * 1024, max_entries=32, clock=monotonic):
        self.revision = revision
        self.ttl, self.max_bytes, self.max_entries = ttl, max_bytes, max_entries
        self.clock = clock
        self.entries = OrderedDict()
        self.size = 0
        self.version = None
        self.lock = Lock()

    def response(self, key, build):
        # One build at a time also prevents duplicate cold requests from doing the same work.
        with self.lock:
            version = self.revision()
            if version != self.version:
                self.entries.clear()
                self.size = 0
                self.version = version
            saved = self.entries.pop(key, None)
            if saved and self.clock() - saved[0] < self.ttl:
                self.entries[key] = saved
                return self._response(saved[1], "HIT")
            if saved:
                self.size -= len(saved[1])
            body = json.dumps(build(), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if self.revision() == version and len(body) <= self.max_bytes:
                while self.entries and (self.size + len(body) > self.max_bytes or len(self.entries) >= self.max_entries):
                    _, (_, removed) = self.entries.popitem(last=False)
                    self.size -= len(removed)
                self.entries[key] = (self.clock(), body)
                self.size += len(body)
            return self._response(body, "MISS")

    @staticmethod
    def _response(body, status):
        return Response(body, media_type="application/json", headers={"X-Catalogue-Cache": status, "Cache-Control": "no-store"})

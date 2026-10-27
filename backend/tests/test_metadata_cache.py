from __future__ import annotations

import logging

from backend.app.metadata_cache import MetadataCache
from backend.tests.fakes import MemoryRedis


def test_cache_aside_tracks_miss_hit_and_configured_ttl() -> None:
    client = MemoryRedis()
    cache = MetadataCache(client, ttl_seconds=17)
    calls = 0
    expected = [{"id": "file-01", "name": "notes.txt"}]

    def load_files() -> list[dict[str, str]]:
        nonlocal calls
        calls += 1
        return expected

    assert cache.list_files(load_files) == expected
    assert cache.list_files(load_files) == expected
    assert calls == 1
    assert client.ttls["clusterdive:files"] == 17
    assert cache.stats() == {
        "cache_hits": 1,
        "cache_misses": 1,
        "cache_errors": 0,
        "cache_hit_rate": 50.0,
        "cache_available": True,
        "cache_ttl_seconds": 17,
    }


def test_cache_invalidation_forces_fresh_metadata_after_a_change() -> None:
    client = MemoryRedis()
    cache = MetadataCache(client, ttl_seconds=10)
    record = {"id": "file-01", "name": "before.txt"}

    assert cache.get_file("file-01", lambda _file_id: dict(record)) == record
    assert cache.get_file("file-01", lambda _file_id: {"id": "file-01", "name": "wrong"}) == record
    record["name"] = "after.txt"
    cache.invalidate_file("file-01")

    assert cache.get_file("file-01", lambda _file_id: dict(record)) == record
    assert cache.stats()["cache_misses"] == 2
    assert cache.stats()["cache_hits"] == 1


def test_redis_outage_logs_and_falls_back_to_metadata_loader(caplog) -> None:
    client = MemoryRedis()
    cache = MetadataCache(client, ttl_seconds=10)
    client.fail = True
    expected = [{"id": "file-01", "name": "catalog.txt"}]

    with caplog.at_level(logging.WARNING):
        actual = cache.list_files(lambda: expected)

    assert actual == expected
    assert cache.stats()["cache_available"] is False
    assert cache.stats()["cache_errors"] >= 2
    assert "catalog fallback" in caplog.text

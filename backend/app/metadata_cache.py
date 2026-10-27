from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Protocol

from redis import Redis, RedisError

logger = logging.getLogger(__name__)


class RedisCacheClient(Protocol):
    def get(self, name: Any) -> Any: ...

    def setex(self, name: Any, time: Any, value: Any) -> Any: ...

    def delete(self, *names: Any) -> Any: ...

    def close(self) -> None: ...


class MetadataCache:
    """Redis cache-aside helper with catalog fallback and observable metrics."""

    _FILES_KEY = "clusterdive:files"
    _FILE_KEY_PREFIX = "clusterdive:file:"

    def __init__(self, client: RedisCacheClient, ttl_seconds: int = 60) -> None:
        if ttl_seconds < 1:
            raise ValueError("Metadata cache TTL must be greater than zero.")
        self._client = client
        self.ttl_seconds = ttl_seconds
        self._hits = 0
        self._misses = 0
        self._errors = 0
        self._available: bool | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_url(cls, url: str, ttl_seconds: int = 60) -> MetadataCache:
        return cls(Redis.from_url(url, decode_responses=True), ttl_seconds)

    def get_file(
        self,
        file_id: str,
        loader: Callable[[str], dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        key = f"{self._FILE_KEY_PREFIX}{file_id}"
        cached = self._get(key)
        if cached is not None:
            try:
                return json.loads(cached)
            except json.JSONDecodeError as error:
                self._record_error("decode", error)
                self._delete_corrupt(key)
        record = loader(file_id)
        if record is not None:
            self._set(key, record)
        return record

    def list_files(
        self,
        loader: Callable[[], list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        cached = self._get(self._FILES_KEY)
        if cached is not None:
            try:
                return json.loads(cached)
            except json.JSONDecodeError as error:
                self._record_error("decode", error)
                self._delete_corrupt(self._FILES_KEY)
        records = loader()
        self._set(self._FILES_KEY, records)
        return records

    def invalidate_file(self, file_id: str) -> None:
        try:
            self._client.delete(self._FILES_KEY, f"{self._FILE_KEY_PREFIX}{file_id}")
            self._set_available(True)
        except RedisError as error:
            self._record_error("invalidate", error)

    def stats(self) -> dict[str, int | float | bool | None]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total * 100 if total else None
            return {
                "cache_hits": self._hits,
                "cache_misses": self._misses,
                "cache_errors": self._errors,
                "cache_hit_rate": hit_rate,
                "cache_available": self._available,
                "cache_ttl_seconds": self.ttl_seconds,
            }

    def close(self) -> None:
        self._client.close()

    def _get(self, key: str) -> str | None:
        try:
            value = self._client.get(key)
            if value is not None and not isinstance(value, str):
                raise RedisError("Redis returned a non-text cache entry.")
        except RedisError as error:
            with self._lock:
                self._misses += 1
            self._record_error("read", error)
            return None
        self._set_available(True)
        with self._lock:
            if value is None:
                self._misses += 1
                return None
            self._hits += 1
        return value

    def _set(self, key: str, value: Any) -> None:
        try:
            encoded = json.dumps(value, ensure_ascii=False)
            self._client.setex(key, self.ttl_seconds, encoded)
            self._set_available(True)
        except (RedisError, TypeError, ValueError) as error:
            self._record_error("write", error)

    def _set_available(self, available: bool) -> None:
        with self._lock:
            self._available = available

    def _delete_corrupt(self, key: str) -> None:
        try:
            self._client.delete(key)
        except RedisError as error:
            self._record_error("delete corrupt entry", error)

    def _record_error(self, operation: str, error: Exception) -> None:
        with self._lock:
            self._errors += 1
            self._available = False
        logger.warning("Redis metadata cache %s failed; using catalog fallback: %s", operation, error)

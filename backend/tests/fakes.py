from __future__ import annotations

from redis.exceptions import RedisError


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail = False
        self.closed = False

    def get(self, name: str) -> str | None:
        self._raise_if_unavailable()
        return self.values.get(name)

    def setex(self, name: str, time: int, value: str) -> None:
        self._raise_if_unavailable()
        self.values[name] = value
        self.ttls[name] = time

    def delete(self, *keys: str) -> int:
        self._raise_if_unavailable()
        deleted = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                self.ttls.pop(key, None)
                deleted += 1
        return deleted

    def close(self) -> None:
        self.closed = True

    def _raise_if_unavailable(self) -> None:
        if self.fail:
            raise RedisError("test Redis outage")


class MemoryRaft:
    def __init__(self) -> None:
        self.operations: list[dict] = []
        self.closed = False

    def commit_operation(self, operation: dict) -> dict:
        self.operations.append(operation)
        return {
            "committed": True,
            "index": len(self.operations),
            "term": 1,
            "leader_id": "metadata-01",
            "operation_id": operation.get("operation_id", f"test-{len(self.operations)}"),
        }

    def status(self) -> dict:
        nodes = []
        for index in range(1, 4):
            node_id = f"metadata-{index:02d}"
            nodes.append({
                "node_id": node_id,
                "address": f"127.0.0.1:{50160 + index}",
                "reachable": True,
                "role": "leader" if index == 1 else "follower",
                "term": 1,
                "leader_id": "metadata-01",
                "commit_index": len(self.operations),
                "last_applied": len(self.operations),
                "last_log_index": len(self.operations),
                "last_log_term": 1 if self.operations else 0,
                "heartbeat_age_ms": 10,
                "heartbeat_state": "leader" if index == 1 else "recent",
                "recent_entries": [],
                "error": None,
            })
        return {
            "node_count": 3,
            "reachable_nodes": 3,
            "quorum_required": 2,
            "quorum_available": True,
            "leader_id": "metadata-01",
            "nodes": nodes,
            "recent_entries": [],
            "implementation": "educational-raft",
        }

    def close(self) -> None:
        self.closed = True

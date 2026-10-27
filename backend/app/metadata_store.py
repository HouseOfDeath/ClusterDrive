from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid
from typing import Any, Callable

ConsensusCommit = Callable[[dict[str, Any]], dict[str, Any]]


class MetadataStore:
    """Local API catalog whose mutations can be gated by a Raft commit."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._files: dict[str, dict[str, Any]] = {}
        self._logs: list[dict[str, Any]] = []
        self._consensus_commit: ConsensusCommit | None = None
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                self._files = payload.get("files", {})
                self._logs = payload.get("logs", [])
            except (OSError, json.JSONDecodeError, AttributeError) as error:
                raise RuntimeError(
                    f"Could not read metadata catalog at {self.path}: {error}"
                ) from error

    def set_consensus_commit(self, callback: ConsensusCommit) -> None:
        self._consensus_commit = callback

    def list_files(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public_file(record) for record in self._files.values()]

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._files.get(file_id)
            return self._public_file(record) if record else None

    def get_file_for_storage(self, file_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._files.get(file_id)
            return json.loads(json.dumps(record)) if record else None

    def list_files_for_storage(self) -> list[dict[str, Any]]:
        with self._lock:
            return json.loads(json.dumps(list(self._files.values())))

    def update_replica_status(
        self,
        file_id: str,
        chunk_id: str,
        target_node_id: str,
        replica_status: str,
        version: int,
        error: str | None = None,
        logical_clock: int | None = None,
        log_node_id: str | None = None,
        replica_node_id: str | None = None,
    ) -> bool:
        with self._lock:
            record = self._files.get(file_id)
            if record is None:
                return False
            replica = next(
                (
                    replica
                    for chunk in record["chunks"]
                    if chunk["chunk_id"] == chunk_id
                    for replica in chunk["replicas"]
                    if replica["node_id"] == target_node_id
                ),
                None,
            )
            if replica is None:
                return False
            old_replica = dict(replica)
            prior_logs = self._logs
            synchronized_at = datetime.now(UTC).isoformat() if replica_status == "synchronized" else None
            event = self._new_event(
                "Replica synchronization " + replica_status,
                f"File {file_id}, chunk {chunk_id}, node {target_node_id}"
                + (f": {error}" if error else ""),
                "success" if replica_status == "synchronized" else "warning",
                logical_clock,
                log_node_id,
            )
            self._commit_operation({
                "kind": "replica_update",
                "file_id": file_id,
                "chunk_id": chunk_id,
                "target_node_id": target_node_id,
                "replica_node_id": replica_node_id or target_node_id,
                "status": replica_status,
                "version": version,
                "error": error,
                "synchronized_at": synchronized_at,
                "event": event,
            })
            replica["node_id"] = replica_node_id or target_node_id
            replica["status"] = replica_status
            replica["version"] = version if replica_status == "synchronized" else replica.get("version", 0)
            replica["error"] = error
            if synchronized_at is not None:
                replica["synchronized_at"] = synchronized_at
            self._logs = [event, *self._logs[:199]]
            try:
                self._save()
            except OSError:
                replica.clear()
                replica.update(old_replica)
                self._logs = prior_logs
                raise
            return True

    def add_file(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._commit_operation({"kind": "file_upsert", "record": record})
            self._files[record["id"]] = record
            try:
                self._save()
            except OSError:
                self._files.pop(record["id"], None)
                raise

    def add_file_and_event(
        self,
        record: dict[str, Any],
        description: str,
        logical_clock: int | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            event = self._new_event(
                "File uploaded",
                description,
                "success",
                logical_clock,
                node_id,
            )
            self._commit_operation({
                "kind": "file_upsert",
                "record": record,
                "event": event,
            })
            prior_logs = self._logs
            self._files[record["id"]] = record
            self._logs = [event, *prior_logs[:199]]
            try:
                self._save()
            except OSError:
                self._files.pop(record["id"], None)
                self._logs = prior_logs
                raise
            return self._public_file(record)

    def delete_file(self, file_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._files.get(file_id)
            if record is None:
                return None
            self._commit_operation({"kind": "file_delete", "file_id": file_id})
            self._files.pop(file_id)
            try:
                self._save()
            except OSError:
                self._files[file_id] = record
                raise
            return self._public_file(record)

    def append_event(
        self,
        event: str,
        description: str,
        status: str = "success",
        logical_clock: int | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._new_event(event, description, status, logical_clock, node_id)
            self._commit_operation({"kind": "activity_append", "event": record})
            prior_logs = self._logs
            self._logs = [record, *prior_logs[:199]]
            try:
                self._save()
            except OSError:
                self._logs = prior_logs
                raise
            return record

    def delete_file_and_event(
        self,
        file_id: str,
        logical_clock: int | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            record = self._files.get(file_id)
            if record is None:
                return None
            event = self._new_event(
                "File deleted",
                record["name"],
                "success",
                logical_clock,
                node_id,
            )
            self._commit_operation({
                "kind": "file_delete",
                "file_id": file_id,
                "event": event,
            })
            prior_logs = self._logs
            self._files.pop(file_id)
            self._logs = [event, *prior_logs[:199]]
            try:
                self._save()
            except OSError:
                self._files[file_id] = record
                self._logs = prior_logs
                raise
            return self._public_file(record)

    def _commit_operation(self, operation: dict[str, Any]) -> None:
        if self._consensus_commit is not None:
            self._consensus_commit(operation)

    def list_logs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(record) for record in self._logs]

    @staticmethod
    def _public_file(record: dict[str, Any]) -> dict[str, Any]:
        chunks = record["chunks"]
        replicas = [replica for chunk in chunks for replica in chunk["replicas"]]
        synced_counts = [
            sum(replica.get("status", "synchronized") == "synchronized" for replica in chunk["replicas"])
            for chunk in chunks
        ]
        replication_status = (
            "failed" if any(replica.get("status") == "failed" for replica in replicas)
            else "pending" if any(replica.get("status") == "pending" for replica in replicas)
            else "degraded" if record.get("replication_degraded")
            else "synchronized"
        )
        return {
            "id": record["id"],
            "name": record["name"],
            "size_bytes": record["size_bytes"],
            "content_type": record.get("content_type"),
            "created_at": record["created_at"],
            "replica_count": min(synced_counts, default=0),
            "chunk_count": len(chunks),
            "replication_degraded": bool(record.get("replication_degraded", False)),
            "replication_status": replication_status,
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            {"files": self._files, "logs": self._logs},
            ensure_ascii=False,
            indent=2,
        )
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temporary_path = Path(handle.name)
        try:
            with handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _new_event(
        event: str,
        description: str,
        status: str,
        logical_clock: int | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": uuid.uuid4().hex,
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "description": description,
            "status": status,
            "logical_clock": logical_clock,
            "node_id": node_id,
        }

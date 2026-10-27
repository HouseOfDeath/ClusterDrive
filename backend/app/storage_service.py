from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
import logging
from pathlib import Path
import threading
import uuid
from typing import Any

from fastapi import HTTPException, UploadFile, status

from backend.algorithms.deadlock import WaitForGraph
from backend.algorithms.ricart_agrawala import RicartAgrawalaCluster
from backend.app.metadata_store import MetadataStore
from backend.app.metadata_cache import MetadataCache
from backend.app.models import FeatureStatus
from backend.app.state import INITIAL_FEATURES
from backend.metadata.client import MetadataConsensus, RaftClusterClient, RaftUnavailableError
from backend.storage.client import (
    HealthyNode,
    StorageNodeClient,
    StorageRpcError,
    checksum_bytes,
    order_nodes,
)
from backend.storage.config import (
    StorageNodeConfig,
    chunk_size_bytes,
    configured_storage_nodes,
    metadata_path,
    metadata_cache_ttl_seconds,
    replication_factor,
    redis_url,
    storage_rpc_timeout_seconds,
)

logger = logging.getLogger(__name__)


class ClusterStorageService:
    def __init__(
        self,
        nodes: list[StorageNodeConfig] | None = None,
        catalog: MetadataStore | None = None,
        chunk_size: int | None = None,
        replica_count: int | None = None,
        rpc_timeout: float | None = None,
        cache: MetadataCache | None = None,
        raft_client: MetadataConsensus | None = None,
    ) -> None:
        self.nodes = nodes if nodes is not None else configured_storage_nodes()
        self.catalog = catalog if catalog is not None else MetadataStore(metadata_path())
        self.chunk_size = chunk_size if chunk_size is not None else chunk_size_bytes()
        self.replica_count = replica_count if replica_count is not None else replication_factor()
        self.rpc_timeout = rpc_timeout if rpc_timeout is not None else storage_rpc_timeout_seconds()
        if self.chunk_size < 1:
            raise ValueError("Chunk size must be greater than zero.")
        if self.replica_count < 1:
            raise ValueError("Replica count must be greater than zero.")
        if self.rpc_timeout <= 0:
            raise ValueError("Storage RPC timeout must be greater than zero.")
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Storage node IDs must be unique.")
        self.clients = {
            node.node_id: StorageNodeClient(node, timeout_seconds=self.rpc_timeout)
            for node in self.nodes
        }
        self.cache = cache if cache is not None else MetadataCache.from_url(
            redis_url(),
            metadata_cache_ttl_seconds(),
        )
        self.raft = raft_client if raft_client is not None else RaftClusterClient()
        self.catalog.set_consensus_commit(self._commit_metadata_operation)
        self.metadata_node_ids = ["metadata-01", "metadata-02", "metadata-03"]
        self.mutex = RicartAgrawalaCluster(self.metadata_node_ids)
        self.last_deadlock_demo: dict[str, Any] | None = None
        self._replication_executor = ThreadPoolExecutor(max_workers=8)
        self._replication_futures: list[tuple[str, Future[None]]] = []
        self._replication_futures_lock = threading.Lock()
        self._replica_state_lock = threading.RLock()
        self._placement_lock = threading.Lock()
        self._placement_cursor = 0
        self._placement_counts = {node_id: 0 for node_id in self.clients}
        self._request_counts = {
            node_id: {"upload": 0, "replication": 0, "download": 0, "delete": 0}
            for node_id in self.clients
        }
        self._metrics_lock = threading.Lock()
        self.replication_demo: dict[str, Any] | None = None
        self._demo_chunk_id: str | None = None

    def close(self) -> None:
        self._replication_executor.shutdown(wait=True, cancel_futures=False)
        if self._demo_chunk_id is not None:
            for client in self.clients.values():
                try:
                    client.delete_chunk(self._demo_chunk_id)
                except StorageRpcError:
                    logger.warning("Could not clean up controlled replication demo chunk on %s", client.config.node_id)
        self.cache.close()
        self.raft.close()
        for client in self.clients.values():
            client.close()

    def healthy_nodes(self) -> tuple[list[tuple[StorageNodeClient, HealthyNode]], dict[str, str]]:
        healthy: list[tuple[StorageNodeClient, HealthyNode]] = []
        failures: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(self.clients))) as executor:
            futures = {
                executor.submit(client.check_health): client
                for client in self.clients.values()
            }
            for future, client in futures.items():
                try:
                    healthy.append((client, future.result()))
                except StorageRpcError as error:
                    failures[client.config.node_id] = str(error)
        healthy.sort(key=lambda item: item[0].config.node_id)
        return healthy, failures

    def dashboard(self) -> dict[str, Any]:
        files = self.list_files()
        nodes, _ = self.healthy_nodes()
        features = dict(INITIAL_FEATURES)
        features["upload_availability"] = FeatureStatus(
            status="implemented" if nodes else "unavailable",
            message=(
                "At least one healthy storage node is available for uploads."
                if nodes
                else "No healthy storage nodes are currently available for uploads."
            ),
        )
        replication = self.replication_status()
        features["replication"] = FeatureStatus(
            status="unavailable" if not nodes else "implemented",
            message=(
                f"{replication['synchronized']} synchronized, "
                f"{replication['pending']} pending, and {replication['failed']} failed replica copies."
                + (
                    f" Currently {len(nodes)} healthy nodes are available for a target of {self.replica_count}."
                    if len(nodes) < self.replica_count
                    else ""
                )
            ),
        )
        raft_status = self.raft.status()
        features["raft"] = FeatureStatus(
            status="implemented" if raft_status["leader_id"] and raft_status["quorum_available"] else "unavailable",
            message=(
                f"Leader {raft_status['leader_id']} is active with a majority."
                if raft_status["leader_id"] and raft_status["quorum_available"]
                else f"Raft is implemented, but no leader with a reachable majority is available "
                f"({raft_status['reachable_nodes']}/{raft_status['node_count']} peers reachable)."
            ),
        )
        cache_stats = self.cache.stats()
        features["redis_cache"] = FeatureStatus(
            status="implemented" if cache_stats["cache_available"] is not False else "unavailable",
            message=(
                f"Redis cache-aside is configured with a {cache_stats['cache_ttl_seconds']} second TTL; "
                + (
                    "Redis is reachable."
                    if cache_stats["cache_available"] is True
                    else "Redis is unavailable; catalog fallback is active."
                    if cache_stats["cache_available"] is False
                    else "Redis reachability will be reported after the first cache request."
                )
            ),
        )
        return {
            "storage_used_bytes": sum(node.storage_used_bytes for _, node in nodes),
            "storage_capacity_bytes": sum(node.storage_capacity_bytes for _, node in nodes),
            "total_files": len(files),
            "active_nodes": len(nodes),
            "total_nodes": len(self.nodes),
            **cache_stats,
            "features": features,
        }

    def list_files(self) -> list[dict[str, Any]]:
        return self.cache.list_files(self.catalog.list_files)

    def cluster_metrics(self) -> dict[str, Any]:
        healthy, _ = self.healthy_nodes()
        with self._metrics_lock:
            placement = dict(self._placement_counts)
            requests = {
                node_id: dict(counts)
                for node_id, counts in self._request_counts.items()
            }
        return {
            **self.cache.stats(),
            "placement_strategy": "health-checked round-robin primary placement; replicas use the next healthy nodes",
            "placement_counts": placement,
            "request_counts": requests,
            "active_nodes": len(healthy),
            "total_nodes": len(self.nodes),
        }

    def raft_status(self) -> dict[str, Any]:
        return self.raft.status()

    def replication_status(self) -> dict[str, Any]:
        records = self.catalog.list_files_for_storage()
        files: list[dict[str, Any]] = []
        totals = {"pending": 0, "synchronized": 0, "failed": 0}
        for record in records:
            chunks = []
            file_states: set[str] = set()
            for chunk in record["chunks"]:
                replicas = []
                for replica in chunk["replicas"]:
                    replica_status = replica.get("status", "synchronized")
                    if replica_status not in totals:
                        replica_status = "failed"
                    totals[replica_status] += 1
                    file_states.add(replica_status)
                    replicas.append({
                        "node_id": replica["node_id"],
                        "status": replica_status,
                        "version": replica.get("version", 1 if replica_status == "synchronized" else 0),
                        "target_version": replica.get("target_version", 1),
                        "error": replica.get("error"),
                    })
                chunks.append({
                    "index": chunk["index"],
                    "chunk_id": chunk["chunk_id"],
                    "replicas": replicas,
                })
            file_status = (
                "failed" if "failed" in file_states
                else "pending" if "pending" in file_states
                else "degraded" if record.get("replication_degraded")
                else "synchronized"
            )
            files.append({
                "file_id": record["id"],
                "name": record["name"],
                "status": file_status,
                "chunks": chunks,
            })
        return {
            "target_replicas": self.replica_count,
            **totals,
            "files": files,
            "demo": dict(self.replication_demo) if self.replication_demo else None,
        }

    def wait_for_replication(self, file_id: str, timeout: float = 5.0) -> None:
        with self._replication_futures_lock:
            futures = [
                future for candidate_id, future in self._replication_futures
                if candidate_id == file_id
            ]
        for future in futures:
            future.result(timeout=timeout)

    def start_replication_demo(self) -> dict[str, Any]:
        healthy, _ = self.healthy_nodes()
        if len(healthy) < 2:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The replication lag demo requires at least two healthy storage nodes.",
            )
        if self._demo_chunk_id is not None:
            for client in self.clients.values():
                try:
                    client.delete_chunk(self._demo_chunk_id)
                except StorageRpcError:
                    logger.warning("Could not remove the previous replication demo chunk from %s", client.config.node_id)
        healthy_clients = [client for client, _ in healthy]
        with self._placement_lock:
            placement = order_nodes(healthy_clients, self._placement_cursor)
            self._placement_cursor += 1
        source, target = placement[:2]
        data = b"ClusterDrive controlled eventual-consistency demonstration"
        chunk_id = uuid.uuid4().hex
        checksum = checksum_bytes(data)
        try:
            source.upload_chunk(chunk_id, data, checksum)
            self._record_node_operation(source.config.node_id, "upload", placed=True)
        except StorageRpcError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not create the demo's primary replica: {error}",
            ) from error
        self._demo_chunk_id = chunk_id
        self.replication_demo = {
            "status": "pending",
            "chunk_id": chunk_id,
            "version": 1,
            "source_node": source.config.node_id,
            "target_node": target.config.node_id,
            "source_status": "synchronized",
            "target_status": "pending",
            "source_version": 1,
            "target_version": 0,
            "error": None,
        }
        return dict(self.replication_demo)

    def converge_replication_demo(self) -> dict[str, Any]:
        demo = self.replication_demo
        if demo is None or demo["status"] != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Start the replication lag demo before requesting convergence.",
            )
        source = self.clients.get(str(demo["source_node"]))
        target = self.clients.get(str(demo["target_node"]))
        if source is None or target is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A demo replica node is no longer configured.")
        try:
            data, received_checksum = source.download_chunk(str(demo["chunk_id"]))
            expected_checksum = checksum_bytes(data)
            if received_checksum != expected_checksum:
                raise StorageRpcError(source.config.node_id, "replication", "source returned data with an invalid checksum.")
            target.upload_chunk(str(demo["chunk_id"]), data, expected_checksum)
            self._record_node_operation(source.config.node_id, "download")
            self._record_node_operation(target.config.node_id, "replication")
            demo.update({
                "status": "synchronized",
                "target_status": "synchronized",
                "target_version": int(demo["version"]),
                "error": None,
            })
        except StorageRpcError as error:
            demo.update({
                "status": "failed",
                "target_status": "failed",
                "error": str(error),
            })
        return dict(demo)

    def _synchronize_replica(
        self,
        file_id: str,
        chunk_id: str,
        source_node: str,
        target_node: str,
        version: int,
        fallback_nodes: tuple[str, ...],
    ) -> None:
        with self._replica_state_lock:
            record = self.cache.get_file(file_id, self.catalog.get_file_for_storage)
            if record is None:
                return
            chunk = next((item for item in record["chunks"] if item["chunk_id"] == chunk_id), None)
            if chunk is None:
                return
            replica = next(
                (item for item in chunk["replicas"] if item["node_id"] == target_node),
                None,
            )
            if replica is None or replica.get("status") != "pending":
                return
            source = self.clients.get(source_node)
            if source is None:
                error_message = f"Source {source_node} is no longer configured."
                self.catalog.update_replica_status(
                    file_id,
                    chunk_id,
                    target_node,
                    "failed",
                    version,
                    error_message,
                    logical_clock=self.mutex.clock_tick("metadata-01"),
                    log_node_id="metadata-01",
                )
                self.cache.invalidate_file(file_id)
                return
            successful_target: str | None = None
            try:
                data, received_checksum = source.download_chunk(chunk_id)
                checksum = checksum_bytes(data)
                if received_checksum != checksum or checksum != chunk["sha256"] or len(data) != chunk["size_bytes"]:
                    raise StorageRpcError(source_node, "replication", "source chunk failed checksum or length verification.")
                self._record_node_operation(source_node, "download")
                failures: list[str] = []
                for candidate_id in (target_node, *fallback_nodes):
                    candidate = self.clients.get(candidate_id)
                    if candidate is None:
                        failures.append(f"Unknown storage node {candidate_id}.")
                        continue
                    self._record_node_operation(candidate_id, "replication")
                    try:
                        candidate.upload_chunk(chunk_id, data, checksum)
                    except StorageRpcError as error:
                        failures.append(str(error))
                        continue
                    successful_target = candidate_id
                    break
                if successful_target is None:
                    raise StorageRpcError(
                        target_node,
                        "replication",
                        "; ".join(failures) or "No healthy replica destination accepted the chunk.",
                    )
                replica_status = "synchronized"
                error_message = None
            except StorageRpcError as error:
                replica_status = "failed"
                error_message = str(error)
            changed = self.catalog.update_replica_status(
                file_id,
                chunk_id,
                target_node,
                replica_status,
                version,
                error_message,
                logical_clock=self.mutex.clock_tick("metadata-01"),
                log_node_id="metadata-01",
                replica_node_id=(
                    successful_target
                    if replica_status == "synchronized"
                    else target_node
                ),
            )
            if changed:
                self.cache.invalidate_file(file_id)
                if error_message:
                    logger.warning("Asynchronous replica synchronization failed: %s", error_message)

    def _record_node_operation(self, node_id: str, operation: str, placed: bool = False) -> None:
        if not node_id:
            return
        with self._metrics_lock:
            counters = self._request_counts.get(node_id)
            if counters is not None and operation in counters:
                counters[operation] += 1
            if placed and node_id in self._placement_counts:
                self._placement_counts[node_id] += 1

    def _commit_metadata_operation(self, operation: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.raft.commit_operation(operation)
        except RaftUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    def algorithm_status(self) -> dict[str, Any]:
        status = self.mutex.snapshot()
        status["last_deadlock_demo"] = (
            dict(self.last_deadlock_demo) if self.last_deadlock_demo is not None else None
        )
        return status

    def run_deadlock_demo(self) -> dict[str, Any]:
        graph = WaitForGraph()
        graph.begin("transaction-01")
        graph.begin("transaction-02")
        graph.acquire("transaction-01", "lock-A")
        graph.acquire("transaction-02", "lock-B")
        graph.acquire("transaction-01", "lock-B")
        graph.acquire("transaction-02", "lock-A")
        result = graph.recover()
        coordinator = self.metadata_node_ids[0]
        clock = self.mutex.clock_tick(coordinator)
        result.update({
            "execution_id": uuid.uuid4().hex,
            "logical_clock": clock,
            "node_id": coordinator,
        })
        self.catalog.append_event(
            "Deadlock recovered",
            f"Detected {' -> '.join(result['cycle'])}; aborted {result['victim']} and released {', '.join(result['released_locks'])}.",
            status="warning",
            logical_clock=clock,
            node_id=coordinator,
        )
        self.last_deadlock_demo = result
        return dict(result)

    def node_records(self) -> list[dict[str, Any]]:
        healthy, failures = self.healthy_nodes()
        healthy_by_id = {node.node_id: node for _, node in healthy}
        files = self.catalog.list_files()
        raw_files = [self.catalog.get_file_for_storage(record["id"]) for record in files]
        records = []
        for config in self.nodes:
            node = healthy_by_id.get(config.node_id)
            file_count = sum(
                1
                for record in raw_files
                if record and any(
                    replica["node_id"] == config.node_id
                    for chunk in record["chunks"]
                    for replica in chunk["replicas"]
                )
            )
            records.append({
                "id": config.node_id,
                "name": config.node_id,
                "status": "healthy" if node else "unavailable",
                "location": None,
                "storage_used_bytes": node.storage_used_bytes if node else 0,
                "storage_capacity_bytes": node.storage_capacity_bytes if node else 0,
                "file_count": file_count,
                "error": failures.get(config.node_id),
            })
        return records

    def upload_file(self, upload: UploadFile) -> dict[str, Any]:
        filename = Path(upload.filename or "unnamed-file").name
        if not filename.strip() or filename in {".", ".."}:
            raise HTTPException(status_code=400, detail="A valid filename is required.")

        healthy, failures = self.healthy_nodes()
        if not healthy:
            detail = "; ".join(failures.values()) or "No storage nodes are configured."
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"No healthy storage nodes are available: {detail}",
            )

        target_replica_count = min(self.replica_count, len(healthy))
        uploaded_locations: list[tuple[StorageNodeClient, str]] = []
        chunks: list[dict[str, Any]] = []
        total_size = 0
        file_id = uuid.uuid4().hex
        chunk_index = 0
        pending_syncs: list[tuple[str, str, str, str, int, tuple[str, ...]]] = []
        try:
            with self.mutex.critical_section("metadata-01", "file-write"):
                while True:
                    chunk_data = upload.file.read(self.chunk_size)
                    if not chunk_data and chunk_index > 0:
                        break
                    chunk_id = uuid.uuid4().hex
                    checksum = checksum_bytes(chunk_data)
                    healthy_clients = [client for client, _ in healthy]
                    with self._placement_lock:
                        placement = order_nodes(healthy_clients, self._placement_cursor)
                        self._placement_cursor += 1
                    selected: list[StorageNodeClient] = []
                    write_errors: list[str] = []
                    for client in placement:
                        if selected:
                            break
                        try:
                            client.upload_chunk(chunk_id, chunk_data, checksum)
                        except StorageRpcError as error:
                            write_errors.append(str(error))
                            continue
                        uploaded_locations.append((client, chunk_id))
                        selected.append(client)
                        self._record_node_operation(client.config.node_id, "upload", placed=True)
                    if not selected:
                        error_summary = "; ".join(write_errors) or "No healthy node accepted the chunk."
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Could not store chunk {chunk_index}: {error_summary}",
                        )
                    for client in placement:
                        if len(selected) >= target_replica_count:
                            break
                        if client in selected:
                            continue
                        selected.append(client)
                    replicas: list[dict[str, Any]] = [{
                        "node_id": selected[0].config.node_id,
                        "sha256": checksum,
                        "version": 1,
                        "target_version": 1,
                        "status": "synchronized",
                        "error": None,
                    }]
                    for client in selected[1:]:
                        replicas.append({
                            "node_id": client.config.node_id,
                            "sha256": checksum,
                            "version": 0,
                            "target_version": 1,
                            "status": "pending",
                            "error": None,
                        })
                        pending_syncs.append((
                            file_id,
                            chunk_id,
                            selected[0].config.node_id,
                            client.config.node_id,
                            1,
                            tuple(
                                candidate.config.node_id
                                for candidate in placement
                                if candidate not in selected
                            ),
                        ))
                    chunks.append({
                        "index": chunk_index,
                        "chunk_id": chunk_id,
                        "size_bytes": len(chunk_data),
                        "sha256": checksum,
                        "replicas": replicas,
                    })
                    total_size += len(chunk_data)
                    chunk_index += 1
                    if not chunk_data:
                        break

                record = {
                    "id": file_id,
                    "name": filename,
                    "size_bytes": total_size,
                    "content_type": upload.content_type,
                    "created_at": datetime.now(UTC).isoformat(),
                    "chunks": chunks,
                    "replication_degraded": target_replica_count < self.replica_count,
                }
                event_clock = self.mutex.clock_tick("metadata-01")
                result = self.catalog.add_file_and_event(
                    record,
                    f"{filename} · {len(chunks)} chunks · {target_replica_count} replicas",
                    logical_clock=event_clock,
                    node_id="metadata-01",
                )
                self.cache.invalidate_file(file_id)
        except Exception:
            self._rollback_chunks(uploaded_locations)
            raise
        for sync in pending_syncs:
            future = self._replication_executor.submit(self._synchronize_replica, *sync)
            with self._replication_futures_lock:
                self._replication_futures.append((file_id, future))
        return result

    def download_file(self, file_id: str) -> tuple[bytes, dict[str, Any]]:
        record = self.cache.get_file(file_id, self.catalog.get_file_for_storage)
        if record is None:
            raise HTTPException(status_code=404, detail=f"File {file_id} was not found.")
        output = bytearray()
        for chunk in sorted(record["chunks"], key=lambda item: item["index"]):
            data, failures = self._download_chunk(chunk)
            if data is None:
                detail = "; ".join(failures) or "No replicas are recorded."
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Chunk {chunk['index']} ({chunk['chunk_id']}) is missing or corrupt on all replicas: {detail}",
                )
            output.extend(data)
        if len(output) != record["size_bytes"]:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"Reconstructed file has {len(output)} bytes; "
                    f"metadata expects {record['size_bytes']} bytes."
                ),
            )
        event_clock = self.mutex.clock_tick("metadata-01")
        self.catalog.append_event(
            "File downloaded",
            f"{record['name']} · {len(record['chunks'])} chunks",
            logical_clock=event_clock,
            node_id="metadata-01",
        )
        public_record = self.catalog.get_file(file_id)
        if public_record is None:
            raise RuntimeError(f"File metadata disappeared during download: {file_id}")
        return bytes(output), public_record

    def delete_file(self, file_id: str) -> dict[str, Any]:
        failures: list[str] = []
        with self.mutex.critical_section("metadata-01", "file-write"):
            with self._replica_state_lock:
                record = self.catalog.get_file_for_storage(file_id)
                if record is None:
                    raise HTTPException(status_code=404, detail=f"File {file_id} was not found.")
                for chunk in record["chunks"]:
                    for replica in chunk["replicas"]:
                        client = self.clients.get(replica["node_id"])
                        if client is None:
                            failures.append(f"Unknown storage node {replica['node_id']}.")
                            continue
                        try:
                            client.delete_chunk(chunk["chunk_id"])
                            self._record_node_operation(client.config.node_id, "delete")
                        except StorageRpcError as error:
                            failures.append(str(error))
                if failures:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="File data could not be deleted from every replica: " + "; ".join(failures),
                    )
                event_clock = self.mutex.clock_tick("metadata-01")
                deleted = self.catalog.delete_file_and_event(
                    file_id,
                    logical_clock=event_clock,
                    node_id="metadata-01",
                )
                if deleted is None:
                    raise HTTPException(status_code=404, detail=f"File {file_id} was not found.")
                self.cache.invalidate_file(file_id)
        return deleted

    def _download_chunk(self, chunk: dict[str, Any]) -> tuple[bytes | None, list[str]]:
        errors: list[str] = []
        for replica in chunk["replicas"]:
            if replica.get("status", "synchronized") != "synchronized":
                errors.append(
                    f"{replica['node_id']} replica is {replica.get('status', 'unknown')} "
                    f"at version {replica.get('version', 0)}; expected version "
                    f"{replica.get('target_version', 1)}."
                )
                continue
            client = self.clients.get(replica["node_id"])
            if client is None:
                errors.append(f"Unknown storage node {replica['node_id']}.")
                continue
            try:
                data, response_checksum = client.download_chunk(chunk["chunk_id"])
            except StorageRpcError as error:
                errors.append(str(error))
                continue
            actual_checksum = checksum_bytes(data)
            if actual_checksum != chunk["sha256"]:
                errors.append(
                    f"{replica['node_id']} returned corrupt chunk "
                    f"(expected {chunk['sha256']}, received {actual_checksum})."
                )
                continue
            if response_checksum != actual_checksum:
                errors.append(f"{replica['node_id']} returned an inconsistent checksum receipt.")
                continue
            if replica["sha256"] != actual_checksum:
                errors.append(f"{replica['node_id']} replica checksum did not match metadata.")
                continue
            if len(data) != chunk["size_bytes"]:
                errors.append(
                    f"{replica['node_id']} returned {len(data)} bytes; "
                    f"expected {chunk['size_bytes']}."
                )
                continue
            self._record_node_operation(replica["node_id"], "download")
            return data, errors
        return None, errors

    @staticmethod
    def _rollback_chunks(chunks: list[tuple[StorageNodeClient, str]]) -> None:
        for client, chunk_id in chunks:
            try:
                client.delete_chunk(chunk_id)
            except StorageRpcError as error:
                logger.error("Upload rollback failed for chunk %s: %s", chunk_id, error)

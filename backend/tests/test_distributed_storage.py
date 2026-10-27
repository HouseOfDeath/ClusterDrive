from __future__ import annotations

import asyncio
from concurrent import futures
from dataclasses import dataclass
import hashlib
from pathlib import Path
import threading

import grpc
import httpx
import pytest
from fastapi import FastAPI

from backend.app.main import create_app
from backend.app.metadata_cache import MetadataCache
from backend.app.metadata_store import MetadataStore
from backend.app.storage_service import ClusterStorageService
from backend.storage.config import StorageNodeConfig
from backend.storage.client import StorageRpcError
from backend.storage.node import StorageNode
from backend.storage.proto import storage_pb2_grpc
from backend.tests.fakes import MemoryRaft, MemoryRedis


@dataclass
class LiveCluster:
    app: FastAPI
    service: ClusterStorageService
    node_directories: dict[str, Path]
    node_servers: dict[str, grpc.Server]


@pytest.fixture
def cluster(tmp_path: Path):
    configs: list[StorageNodeConfig] = []
    servers: dict[str, grpc.Server] = {}
    directories: dict[str, Path] = {}
    for index in range(3):
        node_id = f"node-{index + 1:02d}"
        directory = tmp_path / "storage" / node_id
        directory.mkdir(parents=True)
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        storage_pb2_grpc.add_StorageServiceServicer_to_server(
            StorageNode(node_id, directory),
            server,
        )
        port = server.add_insecure_port("127.0.0.1:0")
        assert port > 0
        server.start()
        servers[node_id] = server
        directories[node_id] = directory
        configs.append(StorageNodeConfig(node_id, f"127.0.0.1:{port}", directory))

    service = ClusterStorageService(
        nodes=configs,
        catalog=MetadataStore(tmp_path / "metadata.json"),
        chunk_size=7,
        replica_count=2,
        rpc_timeout=1,
        cache=MetadataCache(MemoryRedis(), ttl_seconds=30),
        raft_client=MemoryRaft(),
    )
    application = create_app(service)
    yield LiveCluster(application, service, directories, servers)

    service.close()
    for server in servers.values():
        server.stop(grace=0).wait()


def request(
    app: FastAPI,
    method: str,
    path: str,
    **kwargs,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def upload_bytes(app: FastAPI, filename: str, data: bytes) -> dict:
    response = request(
        app,
        "POST",
        "/api/files",
        files={"file": (filename, data, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_splits_file_replicates_chunks_and_reconstructs_original(cluster: LiveCluster) -> None:
    original = b"distributed-file-data-spanning-several-chunks"

    uploaded = upload_bytes(cluster.app, "research.bin", original)

    assert uploaded["name"] == "research.bin"
    assert uploaded["size_bytes"] == len(original)
    assert uploaded["chunk_count"] == 7
    assert uploaded["replication_degraded"] is False
    cluster.service.wait_for_replication(uploaded["id"])
    stored = cluster.service.catalog.get_file_for_storage(uploaded["id"])
    assert stored is not None
    assert [chunk["index"] for chunk in stored["chunks"]] == list(range(7))
    for chunk in stored["chunks"]:
        assert len(chunk["replicas"]) == 2
        assert {replica["status"] for replica in chunk["replicas"]} == {"synchronized"}
        assert len({replica["node_id"] for replica in chunk["replicas"]}) == 2
        assert chunk["sha256"] == hashlib.sha256(
            next(
                (cluster.node_directories[replica["node_id"]] / f"{chunk['chunk_id']}.chunk").read_bytes()
                for replica in chunk["replicas"]
            )
        ).hexdigest()
    assert {
        replica["node_id"]
        for chunk in stored["chunks"]
        for replica in chunk["replicas"]
    } == set(cluster.node_directories)

    downloaded = request(cluster.app, "GET", f"/api/files/{uploaded['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == original
    assert downloaded.headers["content-disposition"].endswith("filename*=UTF-8''research.bin")
    upload_log = next(
        item for item in request(cluster.app, "GET", "/api/logs").json()["items"]
        if item["event"] == "File uploaded"
    )
    assert upload_log["event"] == "File uploaded"
    assert upload_log["node_id"] == "metadata-01"
    assert upload_log["logical_clock"] > 0


def test_upload_failure_rolls_back_chunks_written_to_storage_nodes(
    cluster: LiveCluster,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for node_id in ("node-01", "node-02", "node-03"):
        client = cluster.service.clients[node_id]

        def fail_upload(*_args, _node_id: str = node_id, **_kwargs) -> int:
            raise StorageRpcError(_node_id, "upload", "injected test failure")

        monkeypatch.setattr(
            client,
            "upload_chunk",
            fail_upload,
        )

    response = request(
        cluster.app,
        "POST",
        "/api/files",
        files={"file": ("partial.bin", b"multiple-chunks", "application/octet-stream")},
    )

    assert response.status_code == 503
    assert cluster.service.catalog.list_files() == []
    assert all(not list(directory.glob("*.chunk")) for directory in cluster.node_directories.values())


def test_secondary_replica_is_pending_until_asynchronous_sync_completes(
    cluster: LiveCluster,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered_sync = threading.Event()
    allow_sync = threading.Event()
    secondary = cluster.service.clients["node-02"]
    original_upload = secondary.upload_chunk

    def pause_secondary(chunk_id: str, data: bytes, checksum: str) -> int:
        entered_sync.set()
        if not allow_sync.wait(timeout=3):
            raise TimeoutError("test did not release the synchronization worker")
        return original_upload(chunk_id, data, checksum)

    monkeypatch.setattr(secondary, "upload_chunk", pause_secondary)
    uploaded = upload_bytes(cluster.app, "eventual.bin", b"lag")
    assert entered_sync.wait(timeout=2)

    pending = cluster.service.replication_status()
    assert pending["pending"] == 1
    replica_statuses = pending["files"][0]["chunks"][0]["replicas"]
    assert {replica["status"] for replica in replica_statuses} == {"pending", "synchronized"}
    stale = next(replica for replica in replica_statuses if replica["status"] == "pending")
    assert stale["version"] < stale["target_version"]

    allow_sync.set()
    cluster.service.wait_for_replication(uploaded["id"])

    converged = cluster.service.replication_status()
    assert converged["pending"] == 0
    assert converged["synchronized"] == 2
    assert all(
        replica["version"] == replica["target_version"] == 1
        for replica in converged["files"][0]["chunks"][0]["replicas"]
    )


def test_round_robin_placement_distributes_chunks_across_healthy_nodes(
    cluster: LiveCluster,
) -> None:
    uploaded = [
        upload_bytes(cluster.app, f"placed-{index}.txt", f"chunk-{index}".encode())
        for index in range(6)
    ]
    for record in uploaded:
        cluster.service.wait_for_replication(record["id"])

    metrics = request(cluster.app, "GET", "/api/metrics").json()

    assert metrics["placement_strategy"].startswith("health-checked round-robin")
    assert metrics["placement_counts"] == {"node-01": 2, "node-02": 2, "node-03": 2}
    assert all(counts["upload"] >= 2 for counts in metrics["request_counts"].values())


def test_file_list_cache_is_invalidated_after_upload(cluster: LiveCluster) -> None:
    initial = request(cluster.app, "GET", "/api/files")
    assert initial.json() == {"items": [], "count": 0}

    uploaded = upload_bytes(cluster.app, "cache-invalidation.txt", b"fresh metadata")
    cluster.service.wait_for_replication(uploaded["id"])
    refreshed = request(cluster.app, "GET", "/api/files")

    assert refreshed.json()["count"] == 1
    assert refreshed.json()["items"][0]["id"] == uploaded["id"]


def test_round_robin_skips_a_node_that_becomes_unhealthy(cluster: LiveCluster) -> None:
    cluster.node_servers["node-01"].stop(grace=0).wait()

    uploaded = upload_bytes(cluster.app, "health-change.txt", b"healthy nodes only")
    cluster.service.wait_for_replication(uploaded["id"])

    metrics = request(cluster.app, "GET", "/api/metrics").json()
    nodes = request(cluster.app, "GET", "/api/nodes").json()["items"]

    assert metrics["active_nodes"] == 2
    assert metrics["placement_counts"]["node-01"] == 0
    assert metrics["placement_counts"]["node-02"] == 2
    assert metrics["placement_counts"]["node-03"] == 1
    assert next(node for node in nodes if node["id"] == "node-01")["status"] == "unavailable"


def test_replica_reports_failed_when_destination_fails_during_sync(
    cluster: LiveCluster,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for node_id in ("node-02", "node-03"):
        target = cluster.service.clients[node_id]

        def fail_replication(*_args, _node_id: str = node_id, **_kwargs) -> int:
            raise StorageRpcError(_node_id, "replication", "node stopped during synchronization")

        monkeypatch.setattr(target, "upload_chunk", fail_replication)
    uploaded = upload_bytes(cluster.app, "replica-failure.txt", b"primary accepted")
    cluster.service.wait_for_replication(uploaded["id"])

    status = request(cluster.app, "GET", "/api/replication/status").json()

    assert status["failed"] == 3
    assert status["synchronized"] == 3
    assert status["pending"] == 0
    replica_states = status["files"][0]["chunks"][0]["replicas"]
    failed = next(replica for replica in replica_states if replica["status"] == "failed")
    assert failed["version"] < failed["target_version"]
    assert "node stopped during synchronization" in failed["error"]


def test_replica_retries_an_alternate_destination_after_sync_failure(
    cluster: LiveCluster,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = cluster.service.clients["node-02"]

    def fail_replication(*_args, **_kwargs) -> int:
        raise StorageRpcError("node-02", "replication", "node stopped during synchronization")

    monkeypatch.setattr(target, "upload_chunk", fail_replication)

    original = b"retry the replica on another healthy node"
    uploaded = upload_bytes(cluster.app, "replica-retry.txt", original)
    cluster.service.wait_for_replication(uploaded["id"])

    stored = cluster.service.catalog.get_file_for_storage(uploaded["id"])
    assert stored is not None
    replicas = stored["chunks"][0]["replicas"]
    first_chunk = stored["chunks"][0]

    assert {replica["node_id"] for replica in replicas} == {"node-01", "node-03"}
    assert {replica["status"] for replica in replicas} == {"synchronized"}
    assert (
        cluster.node_directories["node-03"] / f"{first_chunk['chunk_id']}.chunk"
    ).read_bytes() == original[: first_chunk["size_bytes"]]
    downloaded = request(cluster.app, "GET", f"/api/files/{uploaded['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == original


def test_controlled_replication_demo_exposes_lag_then_real_convergence(
    cluster: LiveCluster,
) -> None:
    started = request(cluster.app, "POST", "/api/replication/demo")
    assert started.status_code == 200
    assert started.json()["status"] == "pending"
    assert started.json()["target_version"] == 0
    target_id = started.json()["target_node"]
    chunk_id = started.json()["chunk_id"]

    converged = request(cluster.app, "POST", "/api/replication/demo/converge")

    assert converged.status_code == 200
    assert converged.json()["status"] == "synchronized"
    assert converged.json()["target_version"] == 1
    assert (cluster.node_directories[target_id] / f"{chunk_id}.chunk").read_bytes() == (
        b"ClusterDrive controlled eventual-consistency demonstration"
    )


def test_download_falls_back_to_another_replica_when_one_node_fails(cluster: LiveCluster) -> None:
    original = b"failure-tolerance-check"
    uploaded = upload_bytes(cluster.app, "resilient.bin", original)
    cluster.service.wait_for_replication(uploaded["id"])
    stored = cluster.service.catalog.get_file_for_storage(uploaded["id"])
    assert stored is not None
    failed_node_id = stored["chunks"][0]["replicas"][0]["node_id"]

    cluster.node_servers[failed_node_id].stop(grace=0).wait()

    nodes = request(cluster.app, "GET", "/api/nodes")
    failed_node = next(node for node in nodes.json()["items"] if node["id"] == failed_node_id)
    assert failed_node["status"] == "unavailable"
    assert "health check failed" in failed_node["error"]

    downloaded = request(cluster.app, "GET", f"/api/files/{uploaded['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == original


def test_download_falls_back_when_first_replica_checksum_is_corrupt(cluster: LiveCluster) -> None:
    original = b"checksum-fallback"
    uploaded = upload_bytes(cluster.app, "checksum.bin", original)
    cluster.service.wait_for_replication(uploaded["id"])
    stored = cluster.service.catalog.get_file_for_storage(uploaded["id"])
    assert stored is not None
    first_chunk = stored["chunks"][0]
    first_replica = first_chunk["replicas"][0]
    corrupt_path = (
        cluster.node_directories[first_replica["node_id"]]
        / f"{first_chunk['chunk_id']}.chunk"
    )
    corrupt_path.write_bytes(b"corrupt-data")

    downloaded = request(cluster.app, "GET", f"/api/files/{uploaded['id']}/download")

    assert downloaded.status_code == 200
    assert downloaded.content == original


def test_download_reports_chunk_number_if_all_replicas_are_corrupt(cluster: LiveCluster) -> None:
    uploaded = upload_bytes(cluster.app, "broken.bin", b"bad-data")
    cluster.service.wait_for_replication(uploaded["id"])
    stored = cluster.service.catalog.get_file_for_storage(uploaded["id"])
    assert stored is not None
    chunk = stored["chunks"][0]
    for replica in chunk["replicas"]:
        (cluster.node_directories[replica["node_id"]] / f"{chunk['chunk_id']}.chunk").write_bytes(b"corrupt")

    response = request(cluster.app, "GET", f"/api/files/{uploaded['id']}/download")

    assert response.status_code == 502
    assert "Chunk 0" in response.json()["detail"]
    assert "corrupt chunk" in response.json()["detail"]


def test_delete_removes_all_chunk_replicas_and_metadata(cluster: LiveCluster) -> None:
    uploaded = upload_bytes(cluster.app, "remove-me.bin", b"delete all copies")
    cluster.service.wait_for_replication(uploaded["id"])
    stored = cluster.service.catalog.get_file_for_storage(uploaded["id"])
    assert stored is not None

    response = request(cluster.app, "DELETE", f"/api/files/{uploaded['id']}")

    assert response.status_code == 200
    assert cluster.service.catalog.get_file(uploaded["id"]) is None
    for chunk in stored["chunks"]:
        for replica in chunk["replicas"]:
            assert not (
                cluster.node_directories[replica["node_id"]]
                / f"{chunk['chunk_id']}.chunk"
            ).exists()
    logs = request(cluster.app, "GET", "/api/logs").json()["items"]
    assert logs[0]["event"] == "File deleted"
    assert any(entry["event"] == "File uploaded" for entry in logs)


def test_single_healthy_node_upload_is_marked_as_degraded(tmp_path: Path) -> None:
    directory = tmp_path / "one-node"
    directory.mkdir()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    storage_pb2_grpc.add_StorageServiceServicer_to_server(
        StorageNode("only-node", directory),
        server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    service = ClusterStorageService(
        nodes=[StorageNodeConfig("only-node", f"127.0.0.1:{port}", directory)],
        catalog=MetadataStore(tmp_path / "metadata.json"),
        chunk_size=8,
        replica_count=2,
        rpc_timeout=1,
        raft_client=MemoryRaft(),
    )
    app = create_app(service)
    try:
        uploaded = upload_bytes(app, "degraded.bin", b"single node")
        assert uploaded["replica_count"] == 1
        assert uploaded["replication_degraded"] is True
    finally:
        service.close()
        server.stop(grace=0).wait()


def test_upload_requires_at_least_one_healthy_storage_node(tmp_path: Path) -> None:
    service = ClusterStorageService(
        nodes=[],
        catalog=MetadataStore(tmp_path / "metadata.json"),
        chunk_size=8,
        replica_count=2,
        raft_client=MemoryRaft(),
    )
    app = create_app(service)
    try:
        response = request(
            app,
            "POST",
            "/api/files",
            files={"file": ("orphan.bin", b"data", "application/octet-stream")},
        )
    finally:
        service.close()

    assert response.status_code == 503
    assert "No healthy storage nodes" in response.json()["detail"]

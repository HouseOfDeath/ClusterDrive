import asyncio
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend.app.main import create_app
from backend.app.metadata_cache import MetadataCache
from backend.app.metadata_store import MetadataStore
from backend.app.storage_service import ClusterStorageService
from backend.tests.fakes import MemoryRaft, MemoryRedis


@pytest.fixture
def api(tmp_path: Path) -> Iterator[FastAPI]:
    service = ClusterStorageService(
        nodes=[],
        catalog=MetadataStore(tmp_path / "metadata.json"),
        cache=MetadataCache(MemoryRedis(), ttl_seconds=30),
        raft_client=MemoryRaft(),
    )
    application = create_app(service)
    yield application
    service.close()


def run_request(
    application: FastAPI,
    method: str,
    path: str,
    **kwargs,
) -> httpx.Response:
    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send_request())


def test_health_returns_api_status(api: FastAPI) -> None:
    response = run_request(api, "GET", "/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "clusterdive-api",
        "version": "0.2.0",
    }


def test_dashboard_returns_live_empty_counts_and_feature_statuses(api: FastAPI) -> None:
    response = run_request(api, "GET", "/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["storage_used_bytes"] == 0
    assert payload["storage_capacity_bytes"] == 0
    assert payload["total_files"] == 0
    assert payload["active_nodes"] == 0
    assert payload["total_nodes"] == 0
    assert payload["cache_hit_rate"] is not None
    assert payload["features"]["raft"]["status"] == "implemented"
    assert payload["features"]["replication"]["status"] == "unavailable"
    assert payload["features"]["file_upload"]["status"] == "implemented"
    assert payload["features"]["upload_availability"]["status"] == "unavailable"
    assert payload["features"]["lamport_clocks"]["status"] == "implemented"
    assert payload["features"]["distributed_locking"]["status"] == "implemented"
    assert payload["features"]["deadlock_detection"]["status"] == "implemented"


def test_files_returns_an_empty_list(api: FastAPI) -> None:
    response = run_request(api, "GET", "/api/files")

    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


def test_nodes_returns_an_empty_list_when_no_nodes_are_configured(api: FastAPI) -> None:
    response = run_request(api, "GET", "/api/nodes")

    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0, "active_count": 0}


def test_logs_returns_an_empty_list(api: FastAPI) -> None:
    response = run_request(api, "GET", "/api/logs")

    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


def test_algorithm_status_returns_live_metadata_node_clocks(api: FastAPI) -> None:
    response = run_request(api, "GET", "/api/algorithms/status")

    assert response.status_code == 200
    payload = response.json()
    assert [node["node_id"] for node in payload["nodes"]] == [
        "metadata-01",
        "metadata-02",
        "metadata-03",
    ]
    assert all(node["logical_clock"] == 0 for node in payload["nodes"])
    assert payload["critical_section_entries"] == {}


def test_controlled_deadlock_endpoint_recovers_and_logs_recovery(api: FastAPI) -> None:
    response = run_request(api, "POST", "/api/algorithms/deadlock-demo")

    assert response.status_code == 200
    result = response.json()
    assert result["cycle_detected"] is True
    assert result["victim"] == "transaction-02"
    assert result["released_locks"] == ["lock-B"]
    assert result["graph_after"] == {"transaction-01": []}
    assert result["node_id"] == "metadata-01"
    assert result["logical_clock"] > 0

    logs = run_request(api, "GET", "/api/logs").json()["items"]
    assert logs[0]["event"] == "Deadlock recovered"
    assert logs[0]["node_id"] == "metadata-01"
    assert logs[0]["logical_clock"] == result["logical_clock"]


def test_metrics_reports_live_cache_and_unavailable_node_counts(api: FastAPI) -> None:
    response = run_request(api, "GET", "/api/metrics")

    assert response.status_code == 200
    metrics = response.json()
    assert metrics["cache_available"] is None
    assert metrics["cache_misses"] >= 0
    assert metrics["placement_strategy"].startswith("health-checked round-robin")
    assert metrics["active_nodes"] == 0
    assert metrics["total_nodes"] == 0


def test_replication_status_reports_empty_actual_state(api: FastAPI) -> None:
    response = run_request(api, "GET", "/api/replication/status")

    assert response.status_code == 200
    assert response.json()["files"] == []
    assert response.json()["pending"] == 0
    assert response.json()["synchronized"] == 0


def test_raft_status_reports_the_metadata_cluster(api: FastAPI) -> None:
    response = run_request(api, "GET", "/api/raft/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["leader_id"] == "metadata-01"
    assert payload["quorum_required"] == 2
    assert payload["quorum_available"] is True
    assert len(payload["nodes"]) == 3


def test_metadata_write_is_sent_through_the_consensus_client(api: FastAPI) -> None:
    store = api.state.storage_service.catalog
    file_id = "raft-write-test"
    chunk_id = "raft-write-chunk"
    store.add_file_and_event({
        "id": file_id,
        "name": "raft-write.txt",
        "size_bytes": 1,
        "created_at": "2026-10-26T00:00:00+00:00",
        "chunks": [{
            "index": 0,
            "chunk_id": chunk_id,
            "size_bytes": 1,
            "sha256": "checksum",
            "replicas": [{
                "node_id": "node-01",
                "status": "pending",
                "version": 0,
                "target_version": 1,
                "sha256": "checksum",
            }],
        }],
    }, "test operation")
    store.update_replica_status(file_id, chunk_id, "node-01", "synchronized", 1)
    store.append_event("Test event", "activity update")
    store.delete_file_and_event(file_id)

    operations = api.state.storage_service.raft.operations
    assert [operation["kind"] for operation in operations] == [
        "file_upsert",
        "replica_update",
        "activity_append",
        "file_delete",
    ]
    assert operations[0]["record"]["id"] == file_id


def test_cors_allows_the_local_vite_origin(api: FastAPI) -> None:
    response = run_request(
        api,
        "OPTIONS",
        "/api/dashboard",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

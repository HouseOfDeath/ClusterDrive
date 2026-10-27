from __future__ import annotations

from dataclasses import dataclass
from concurrent import futures
import asyncio
import json
from pathlib import Path
import socket
import time

import grpc
import httpx
import pytest

from backend.app.main import create_app
from backend.app.metadata_cache import MetadataCache
from backend.app.storage_service import ClusterStorageService
from backend.storage.config import StorageNodeConfig
from backend.storage.node import StorageNode
from backend.storage.proto import storage_pb2_grpc
from backend.metadata.client import RaftClusterClient, RaftUnavailableError
from backend.metadata.config import MetadataPeerConfig
from backend.metadata import raft_pb2
from backend.metadata.raft import RaftNode, start_raft_grpc_server
from backend.app.metadata_store import MetadataStore
from backend.tests.fakes import MemoryRedis


@dataclass
class RunningRaftCluster:
    nodes: dict[str, RaftNode]
    servers: dict[str, grpc.Server]
    peers: list[MetadataPeerConfig]
    client: RaftClusterClient


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture
def raft_cluster(tmp_path: Path):
    peers = [
        MetadataPeerConfig(f"metadata-{index:02d}", f"127.0.0.1:{_free_port()}")
        for index in range(1, 4)
    ]
    targets = {peer.node_id: peer.target for peer in peers}
    nodes: dict[str, RaftNode] = {}
    servers: dict[str, grpc.Server] = {}
    for peer in peers:
        nodes[peer.node_id] = RaftNode(
            peer.node_id,
            {
                node_id: target
                for node_id, target in targets.items()
                if node_id != peer.node_id
            },
            tmp_path / peer.node_id / "raft-state.json",
            election_timeout=(0.28, 0.48),
            heartbeat_interval=0.05,
            rpc_timeout=0.10,
            start_elections=False,
        )
    for peer in peers:
        servers[peer.node_id] = start_raft_grpc_server(nodes[peer.node_id], peer.target)
    for node in nodes.values():
        node.start()
    client = RaftClusterClient(peers, timeout_seconds=0.35)
    cluster = RunningRaftCluster(nodes, servers, peers, client)
    yield cluster
    client.close()
    for server in servers.values():
        server.stop(grace=0).wait()
    for node in nodes.values():
        node.close()


def _wait_for_leader(cluster: RunningRaftCluster, timeout: float = 6) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = cluster.client.status()
        if status["leader_id"]:
            return status
        time.sleep(0.05)
    raise AssertionError("Raft cluster did not elect a leader before the deadline.")


def test_three_nodes_elect_one_leader_and_only_grant_one_vote_per_term(
    raft_cluster: RunningRaftCluster,
) -> None:
    status = _wait_for_leader(raft_cluster)
    leaders = [node for node in status["nodes"] if node["role"] == "leader"]

    assert len(leaders) == 1
    assert status["quorum_available"] is True
    leader_id = status["leader_id"]
    follower = next(node for node in raft_cluster.nodes.values() if node.node_id != leader_id)
    result = follower.request_vote(raft_pb2.RequestVoteRequest(
        term=status["nodes"][0]["term"],
        candidate_id="different-candidate",
        last_log_index=0,
        last_log_term=0,
    ))

    assert result.vote_granted is False


def test_proposal_is_committed_on_a_majority_and_applied_on_each_node(
    raft_cluster: RunningRaftCluster,
    tmp_path: Path,
) -> None:
    _wait_for_leader(raft_cluster)
    store = MetadataStore(tmp_path / "api-catalog.json")
    store.set_consensus_commit(raft_cluster.client.commit_operation)
    record = {
        "id": "raft-test-file",
        "name": "raft-test.txt",
        "size_bytes": 3,
        "created_at": "2026-10-26T00:00:00+00:00",
        "chunks": [],
    }
    store.add_file_and_event(record, "committed through three peers")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if all(
            node.application_state()["files"].get(record["id"]) is not None
            for node in raft_cluster.nodes.values()
        ):
            break
        time.sleep(0.05)

    assert store.get_file(record["id"]) is not None
    for node in raft_cluster.nodes.values():
        applied = node.application_state()
        assert applied["files"][record["id"]]["name"] == record["name"]
        assert applied["logs"][0]["event"] == "File uploaded"
    committed_entries = raft_cluster.client.status()["recent_entries"]
    assert committed_entries[0]["committed"] is True


def test_cluster_elects_a_new_leader_after_the_current_leader_fails(
    raft_cluster: RunningRaftCluster,
) -> None:
    before = _wait_for_leader(raft_cluster)
    failed_leader = before["leader_id"]
    old_term = next(node["term"] for node in before["nodes"] if node["node_id"] == failed_leader)
    raft_cluster.servers[failed_leader].stop(grace=0).wait()
    raft_cluster.nodes[failed_leader].close()

    current: dict | None = None
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        current = raft_cluster.client.status()
        if current["leader_id"] and current["leader_id"] != failed_leader:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(
            f"The remaining majority did not elect a replacement leader: {current}"
        )

    assert current is not None
    new_leader = next(node for node in current["nodes"] if node["node_id"] == current["leader_id"])
    assert new_leader["term"] > old_term
    assert current["reachable_nodes"] == 2


def test_single_survivor_does_not_claim_metadata_commit_without_quorum(
    raft_cluster: RunningRaftCluster,
    tmp_path: Path,
) -> None:
    _wait_for_leader(raft_cluster)
    for peer in raft_cluster.peers[:2]:
        raft_cluster.servers[peer.node_id].stop(grace=0).wait()
        raft_cluster.nodes[peer.node_id].close()

    store = MetadataStore(tmp_path / "api-catalog.json")
    store.set_consensus_commit(raft_cluster.client.commit_operation)
    with pytest.raises(RaftUnavailableError, match="Could not confirm a majority commit"):
        store.add_file_and_event({
            "id": "must-not-commit",
            "name": "quorum.txt",
            "size_bytes": 0,
            "created_at": "2026-10-26T00:00:00+00:00",
            "chunks": [],
        }, "Quorum test")
    assert store.get_file("must-not-commit") is None

    committed_copies = [
        node.application_state()
        for node_id, node in raft_cluster.nodes.items()
        if node_id == raft_cluster.peers[2].node_id
    ]
    assert all(
        not any(event.get("id") == "must-not-commit" for event in state["logs"])
        for state in committed_copies
    )


def test_api_returns_503_and_rolls_back_chunk_if_raft_cannot_commit(
    raft_cluster: RunningRaftCluster,
    tmp_path: Path,
) -> None:
    for peer in raft_cluster.peers[:2]:
        raft_cluster.servers[peer.node_id].stop(grace=0).wait()
        raft_cluster.nodes[peer.node_id].close()

    storage_directory = tmp_path / "storage-node"
    storage_directory.mkdir()
    storage_server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    storage_pb2_grpc.add_StorageServiceServicer_to_server(
        StorageNode("storage-test", storage_directory),
        storage_server,
    )
    storage_port = storage_server.add_insecure_port("127.0.0.1:0")
    assert storage_port > 0
    storage_server.start()
    service = ClusterStorageService(
        nodes=[StorageNodeConfig(
            "storage-test",
            f"127.0.0.1:{storage_port}",
            storage_directory,
        )],
        catalog=MetadataStore(tmp_path / "api-catalog.json"),
        chunk_size=64,
        cache=MetadataCache(MemoryRedis(), ttl_seconds=30),
        raft_client=raft_cluster.client,
    )
    application = create_app(service)

    async def upload():
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/api/files",
                files={"file": ("no-quorum.txt", b"must roll back", "text/plain")},
            )

    try:
        response = asyncio.run(upload())
        assert response.status_code == 503
        assert "Could not confirm a majority commit" in response.json()["detail"]
        assert service.catalog.list_files() == []
        assert list(storage_directory.glob("*.chunk")) == []
    finally:
        service.close()
        storage_server.stop(grace=0).wait()


def test_term_vote_log_and_applied_state_survive_node_restart(tmp_path: Path) -> None:
    state_path = tmp_path / "metadata-01" / "raft-state.json"
    node = RaftNode(
        "metadata-01",
        {"metadata-02": "127.0.0.1:59992"},
        state_path,
        start_elections=False,
    )
    granted = node.request_vote(raft_pb2.RequestVoteRequest(
        term=4,
        candidate_id="metadata-02",
        last_log_index=0,
        last_log_term=0,
    ))
    node.append_entries(raft_pb2.AppendEntriesRequest(
        term=4,
        leader_id="metadata-02",
        entries=[raft_pb2.LogEntry(
            index=1,
            term=4,
            command_json=json.dumps({
                "operation_id": "persisted-op",
                "kind": "activity_append",
                "event": {"id": "persisted-event", "event": "Persisted"},
            }),
        )],
        leader_commit=1,
    ))
    node.close()

    restarted = RaftNode(
        "metadata-01",
        {"metadata-02": "127.0.0.1:59992"},
        state_path,
        start_elections=False,
    )
    try:
        refused = restarted.request_vote(raft_pb2.RequestVoteRequest(
            term=4,
            candidate_id="other-candidate",
            last_log_index=1,
            last_log_term=4,
        ))
        status = restarted.status()

        assert granted.vote_granted is True
        assert refused.vote_granted is False
        assert status["term"] == 4
        assert status["commit_index"] == status["last_applied"] == 1
        assert restarted.application_state()["logs"][0]["id"] == "persisted-event"
    finally:
        restarted.close()

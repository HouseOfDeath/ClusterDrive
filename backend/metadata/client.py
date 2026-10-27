from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import threading
import uuid
from typing import Any, Protocol

import grpc

from backend.metadata import raft_pb2, raft_pb2_grpc
from backend.metadata.config import MetadataPeerConfig, configured_metadata_peers, metadata_rpc_timeout_seconds

logger = logging.getLogger(__name__)


class RaftUnavailableError(RuntimeError):
    """Raised when a metadata operation cannot be committed by a majority."""


class MetadataConsensus(Protocol):
    def commit_operation(self, operation: dict[str, Any]) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class RaftClusterClient:
    def __init__(
        self,
        peers: list[MetadataPeerConfig] | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.peers = peers if peers is not None else configured_metadata_peers()
        if len(self.peers) != 3:
            raise ValueError("The educational Raft client requires exactly three metadata nodes.")
        self.timeout_seconds = timeout_seconds or metadata_rpc_timeout_seconds()
        self._channels = {
            peer.node_id: grpc.insecure_channel(peer.target)
            for peer in self.peers
        }
        self._stubs = {
            peer_id: raft_pb2_grpc.RaftPeerStub(channel)
            for peer_id, channel in self._channels.items()
        }
        self._lock = threading.Lock()
        self._last_leader_id: str | None = None

    def close(self) -> None:
        for channel in self._channels.values():
            channel.close()

    def commit_operation(self, operation: dict[str, Any]) -> dict[str, Any]:
        command = dict(operation)
        command.setdefault("operation_id", uuid.uuid4().hex)
        serialized = json.dumps(command, ensure_ascii=False, separators=(",", ":"))
        cluster_status = self.status()
        leader_id = cluster_status["leader_id"]
        with self._lock:
            if leader_id:
                self._last_leader_id = leader_id
            preferred = self._last_leader_id or leader_id
        ordered_ids = [
            peer.node_id
            for peer in self.peers
            if peer.node_id == preferred
        ] + [
            peer.node_id
            for peer in self.peers
            if peer.node_id != preferred
        ]
        failures: list[str] = []
        for node_id in ordered_ids:
            try:
                response = self._stubs[node_id].Propose(
                    raft_pb2.ProposeRequest(operation_json=serialized),
                    timeout=self.timeout_seconds,
                )
            except grpc.RpcError as error:
                failures.append(f"{node_id}: {error.code().name}")
                continue
            if response.leader_id:
                with self._lock:
                    self._last_leader_id = response.leader_id
            if response.committed:
                return {
                    "committed": True,
                    "index": int(response.index),
                    "term": int(response.term),
                    "leader_id": response.leader_id or node_id,
                    "operation_id": command["operation_id"],
                }
            failures.append(response.error or f"{node_id} did not commit the operation.")
        detail = "; ".join(failures) or "No metadata node accepted the operation."
        raise RaftUnavailableError(
            "Could not confirm a majority commit for the metadata operation. "
            f"Inspect the Raft status before retrying: {detail}"
        )

    def status(self) -> dict[str, Any]:
        def fetch(node_id: str):
            return node_id, self._stubs[node_id].GetStatus(
                raft_pb2.GetStatusRequest(),
                timeout=self.timeout_seconds,
            )

        responses: dict[str, Any] = {}
        failures: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(self.peers)) as executor:
            futures = {
                executor.submit(fetch, peer.node_id): peer.node_id
                for peer in self.peers
            }
            for future, node_id in futures.items():
                try:
                    response_node_id, status = future.result()
                    responses[response_node_id] = status
                except grpc.RpcError as error:
                    failures[node_id] = error.code().name

        nodes = []
        for peer in self.peers:
            status = responses.get(peer.node_id)
            if status is None:
                nodes.append({
                    "node_id": peer.node_id,
                    "address": peer.target,
                    "reachable": False,
                    "role": "unavailable",
                    "term": 0,
                    "leader_id": "",
                    "commit_index": 0,
                    "last_applied": 0,
                    "last_log_index": 0,
                    "last_log_term": 0,
                    "heartbeat_age_ms": None,
                    "heartbeat_state": "unavailable",
                    "recent_entries": [],
                    "error": failures.get(peer.node_id, "Node did not return status."),
                })
                continue
            heartbeat_age = int(status.heartbeat_age_ms)
            heartbeat_state = (
                "leader"
                if status.role == "leader"
                else "recent"
                if heartbeat_age < 2000
                else "stale"
            )
            nodes.append({
                "node_id": status.node_id,
                "address": peer.target,
                "reachable": True,
                "role": status.role,
                "term": int(status.term),
                "leader_id": status.leader_id,
                "commit_index": int(status.commit_index),
                "last_applied": int(status.last_applied),
                "last_log_index": int(status.last_log_index),
                "last_log_term": int(status.last_log_term),
                "heartbeat_age_ms": heartbeat_age,
                "heartbeat_state": heartbeat_state,
                "recent_entries": [
                    {
                        "index": int(entry.index),
                        "term": int(entry.term),
                        "command": json.loads(entry.command_json),
                        "committed": int(entry.index) <= int(status.commit_index),
                    }
                    for entry in status.recent_entries
                ],
                "error": None,
            })
        reachable = sum(node["reachable"] for node in nodes)
        quorum_required = len(self.peers) // 2 + 1
        leaders = {
            node["node_id"]
            for node in nodes
            if node["reachable"] and node["role"] == "leader"
        }
        leader_id = next(iter(leaders)) if len(leaders) == 1 else ""
        entry_by_position: dict[tuple[int, int], dict[str, Any]] = {}
        for node in nodes:
            for entry in node["recent_entries"]:
                key = (entry["index"], entry["term"])
                existing = entry_by_position.get(key)
                if existing is None or (entry["committed"] and not existing["committed"]):
                    entry_by_position[key] = entry
        recent_entries = [
            entry_by_position[key]
            for key in sorted(entry_by_position, reverse=True)[:20]
        ]
        for entry in recent_entries:
            commit_confirmations = sum(
                node["reachable"] and node["commit_index"] >= entry["index"]
                for node in nodes
            )
            entry["committed"] = commit_confirmations >= quorum_required
        return {
            "node_count": len(self.peers),
            "reachable_nodes": reachable,
            "quorum_required": quorum_required,
            "quorum_available": reachable >= quorum_required,
            "leader_id": leader_id,
            "nodes": nodes,
            "recent_entries": recent_entries,
            "implementation": "educational-raft",
        }

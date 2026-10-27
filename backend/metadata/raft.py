from __future__ import annotations

from concurrent import futures
from concurrent.futures import Future
import json
import logging
import os
from pathlib import Path
import random
import threading
import time
from typing import Any

import grpc

from backend.metadata import raft_pb2, raft_pb2_grpc

logger = logging.getLogger(__name__)


def _apply_operation(state: dict[str, Any], operation: dict[str, Any]) -> None:
    kind = operation.get("kind")
    files: dict[str, Any] = state["files"]
    logs: list[dict[str, Any]] = state["logs"]

    if kind == "file_upsert":
        record = operation.get("record")
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise ValueError("Raft file_upsert operation has no valid file record.")
        files[record["id"]] = record
        event = operation.get("event")
        if isinstance(event, dict):
            logs.insert(0, event)
    elif kind == "file_delete":
        files.pop(str(operation["file_id"]), None)
        event = operation.get("event")
        if isinstance(event, dict):
            logs.insert(0, event)
    elif kind == "replica_update":
        record = files.get(str(operation["file_id"]))
        if isinstance(record, dict):
            for chunk in record.get("chunks", []):
                if chunk.get("chunk_id") != operation["chunk_id"]:
                    continue
                replica = next(
                    (
                        item
                        for item in chunk.get("replicas", [])
                        if item.get("node_id") == operation["target_node_id"]
                    ),
                    None,
                )
                if replica is not None:
                    replica["node_id"] = operation.get("replica_node_id") or operation["target_node_id"]
                    replica["status"] = operation["status"]
                    replica["version"] = operation["version"] if operation["status"] == "synchronized" else replica.get("version", 0)
                    replica["error"] = operation.get("error")
                    if operation["status"] == "synchronized":
                        replica["synchronized_at"] = operation["synchronized_at"]
                break
        event = operation.get("event")
        if isinstance(event, dict):
            logs.insert(0, event)
    elif kind == "activity_append":
        event = operation.get("event")
        if not isinstance(event, dict):
            raise ValueError("Raft activity_append operation has no event.")
        logs.insert(0, event)
    else:
        raise ValueError(f"Unsupported committed Raft metadata operation: {kind!r}.")

    del logs[200:]


class RaftNode:
    """A small, persistent Raft peer intended for local teaching and testing."""

    def __init__(
        self,
        node_id: str,
        peer_targets: dict[str, str],
        state_path: Path,
        election_timeout: tuple[float, float] = (0.65, 1.05),
        heartbeat_interval: float = 0.12,
        rpc_timeout: float = 0.25,
        start_elections: bool = True,
    ) -> None:
        if not node_id or node_id in peer_targets:
            raise ValueError("A Raft node needs a unique ID not present in its peer map.")
        if not peer_targets:
            raise ValueError("A Raft node must be configured with at least one peer.")
        if election_timeout[0] <= heartbeat_interval or election_timeout[1] <= election_timeout[0]:
            raise ValueError("Election timeouts must be ordered and longer than the heartbeat interval.")
        self.node_id = node_id
        self.peer_targets = dict(peer_targets)
        self.state_path = state_path
        self.election_timeout = election_timeout
        self.heartbeat_interval = heartbeat_interval
        self.rpc_timeout = rpc_timeout
        self._lock = threading.RLock()
        self._replication_lock = threading.Lock()
        self._stop = threading.Event()
        self._role = "follower"
        self._term = 0
        self._voted_for: str | None = None
        self._leader_id: str | None = None
        self._log: list[dict[str, Any]] = []
        self._commit_index = 0
        self._last_applied = 0
        self._application_state: dict[str, Any] = {"files": {}, "logs": []}
        self._last_leader_contact = time.monotonic()
        self._election_deadline = 0.0
        self._next_index: dict[str, int] = {}
        self._match_index: dict[str, int] = {}
        self._peer_channels = {
            peer_id: grpc.insecure_channel(target)
            for peer_id, target in self.peer_targets.items()
        }
        self._peer_stubs = {
            peer_id: raft_pb2_grpc.RaftPeerStub(channel)
            for peer_id, channel in self._peer_channels.items()
        }
        self._replication_pool = futures.ThreadPoolExecutor(
            max_workers=len(self._peer_stubs),
            thread_name_prefix=f"raft-replicate-{node_id}",
        )
        self._load_state()
        with self._lock:
            self._apply_committed_locked()
            self._reset_election_deadline_locked()
        self._election_thread = threading.Thread(
            target=self._run,
            name=f"raft-{node_id}",
            daemon=True,
        )
        self._started = False
        if start_elections:
            self.start()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._election_thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._election_thread.is_alive():
            self._election_thread.join(timeout=2)
        self._replication_pool.shutdown(wait=True, cancel_futures=True)
        for channel in self._peer_channels.values():
            channel.close()

    def request_vote(self, request: raft_pb2.RequestVoteRequest) -> raft_pb2.RequestVoteResponse:
        with self._lock:
            if request.term < self._term:
                return raft_pb2.RequestVoteResponse(term=self._term, vote_granted=False)
            if request.term > self._term:
                self._become_follower_locked(request.term, None)
            last_index, last_term = self._last_log_position_locked()
            candidate_is_up_to_date = (
                request.last_log_term > last_term
                or (request.last_log_term == last_term and request.last_log_index >= last_index)
            )
            vote_granted = (
                candidate_is_up_to_date
                and self._voted_for in (None, request.candidate_id)
            )
            if vote_granted:
                self._voted_for = request.candidate_id
                self._leader_id = None
                self._reset_election_deadline_locked()
                self._persist_locked()
            return raft_pb2.RequestVoteResponse(
                term=self._term,
                vote_granted=vote_granted,
            )

    def append_entries(self, request: raft_pb2.AppendEntriesRequest) -> raft_pb2.AppendEntriesResponse:
        with self._lock:
            if request.term < self._term:
                return raft_pb2.AppendEntriesResponse(
                    term=self._term,
                    success=False,
                    conflict_index=len(self._log) + 1,
                )
            if request.term > self._term or self._role != "follower":
                self._become_follower_locked(request.term, request.leader_id)
            else:
                self._leader_id = request.leader_id
            self._last_leader_contact = time.monotonic()
            self._reset_election_deadline_locked()

            if request.previous_log_index > len(self._log):
                return raft_pb2.AppendEntriesResponse(
                    term=self._term,
                    success=False,
                    conflict_index=len(self._log) + 1,
                )
            if request.previous_log_index > 0:
                previous = self._log[request.previous_log_index - 1]
                if previous["term"] != request.previous_log_term:
                    conflicting_term = previous["term"]
                    conflict_index = request.previous_log_index
                    while conflict_index > 1 and self._log[conflict_index - 2]["term"] == conflicting_term:
                        conflict_index -= 1
                    return raft_pb2.AppendEntriesResponse(
                        term=self._term,
                        success=False,
                        conflict_index=conflict_index,
                    )

            changed = False
            for incoming in request.entries:
                entry = {
                    "index": int(incoming.index),
                    "term": int(incoming.term),
                    "command_json": incoming.command_json,
                }
                if entry["index"] <= len(self._log):
                    current = self._log[entry["index"] - 1]
                    if current["term"] != entry["term"] or current["command_json"] != entry["command_json"]:
                        del self._log[entry["index"] - 1:]
                        self._log.append(entry)
                        changed = True
                elif entry["index"] == len(self._log) + 1:
                    self._log.append(entry)
                    changed = True
                else:
                    return raft_pb2.AppendEntriesResponse(
                        term=self._term,
                        success=False,
                        conflict_index=len(self._log) + 1,
                    )

            if request.leader_commit > self._commit_index:
                self._commit_index = min(request.leader_commit, len(self._log))
                self._apply_committed_locked()
                changed = True
            if changed:
                self._persist_locked()
            return raft_pb2.AppendEntriesResponse(
                term=self._term,
                success=True,
                match_index=request.previous_log_index + len(request.entries),
            )

    def propose(self, operation_json: str) -> raft_pb2.ProposeResponse:
        operation = json.loads(operation_json)
        operation_id = operation.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Raft metadata operations require an operation_id.")
        with self._lock:
            if self._role != "leader":
                return raft_pb2.ProposeResponse(
                    accepted=False,
                    committed=False,
                    term=self._term,
                    leader_id=self._leader_id or "",
                    error="This metadata node is not the current leader.",
                )
            existing = next(
                (
                    entry
                    for entry in self._log
                    if json.loads(entry["command_json"]).get("operation_id") == operation_id
                ),
                None,
            )
            if existing is not None:
                entry_index = int(existing["index"])
                term = self._term
            else:
                entry_index = len(self._log) + 1
                term = self._term
                self._log.append({
                    "index": entry_index,
                    "term": term,
                    "command_json": operation_json,
                })
                self._persist_locked()

        self._replicate_round()
        with self._lock:
            committed = self._commit_index >= entry_index
            return raft_pb2.ProposeResponse(
                accepted=True,
                committed=committed,
                term=self._term,
                index=entry_index,
                leader_id=self._leader_id or self.node_id,
                error="" if committed else "The operation has not reached a majority; it remains uncommitted.",
            )

    def status(self, include_log: int = 20) -> dict[str, Any]:
        with self._lock:
            last_index, last_term = self._last_log_position_locked()
            heartbeat_age = max(0, int((time.monotonic() - self._last_leader_contact) * 1000))
            entries = [
                {
                    "index": entry["index"],
                    "term": entry["term"],
                    "command": json.loads(entry["command_json"]),
                }
                for entry in self._log[-include_log:]
            ]
            return {
                "node_id": self.node_id,
                "role": self._role,
                "term": self._term,
                "leader_id": self._leader_id or "",
                "commit_index": self._commit_index,
                "last_applied": self._last_applied,
                "last_log_index": last_index,
                "last_log_term": last_term,
                "heartbeat_age_ms": heartbeat_age,
                "recent_entries": entries,
            }

    def application_state(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._application_state))

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                role = self._role
                remaining = self._election_deadline - time.monotonic()
            if role == "leader":
                self._replicate_round()
                self._stop.wait(self.heartbeat_interval)
            elif remaining <= 0:
                self._start_election()
            else:
                self._stop.wait(min(remaining, 0.05))

    def _start_election(self) -> None:
        with self._lock:
            self._role = "candidate"
            self._term += 1
            election_term = self._term
            self._voted_for = self.node_id
            self._leader_id = None
            self._last_leader_contact = time.monotonic()
            self._reset_election_deadline_locked()
            last_index, last_term = self._last_log_position_locked()
            self._persist_locked()
        votes = 1
        request = raft_pb2.RequestVoteRequest(
            term=election_term,
            candidate_id=self.node_id,
            last_log_index=last_index,
            last_log_term=last_term,
        )
        for peer_id, stub in self._peer_stubs.items():
            if self._stop.is_set():
                return
            try:
                response = stub.RequestVote(request, timeout=self.rpc_timeout)
            except grpc.RpcError as error:
                logger.debug("Raft vote request from %s to %s failed: %s", self.node_id, peer_id, error)
                continue
            with self._lock:
                if response.term > self._term:
                    self._become_follower_locked(response.term, None)
                    return
                if self._role != "candidate" or self._term != election_term:
                    return
            if response.vote_granted:
                votes += 1
        if votes >= self._majority:
            with self._lock:
                if self._role == "candidate" and self._term == election_term:
                    self._role = "leader"
                    self._leader_id = self.node_id
                    self._next_index = {
                        peer_id: len(self._log) + 1
                        for peer_id in self._peer_stubs
                    }
                    self._match_index = {peer_id: 0 for peer_id in self._peer_stubs}
                    self._last_leader_contact = time.monotonic()
                    logger.info("Raft leader elected: %s for term %d", self.node_id, self._term)
                    self._persist_locked()

    def _replicate_round(self) -> None:
        with self._replication_lock:
            with self._lock:
                if self._role != "leader":
                    return
                peers = tuple(self._peer_stubs.items())
            attempts: list[Future[None]] = [
                self._replication_pool.submit(self._replicate_peer, peer_id, stub)
                for peer_id, stub in peers
            ]
            for attempt in attempts:
                try:
                    attempt.result()
                except Exception:
                    logger.exception("Unexpected Raft replication error on %s", self.node_id)
            with self._lock:
                if self._role == "leader":
                    self._advance_commit_locked()

    def _replicate_peer(self, peer_id: str, stub: raft_pb2_grpc.RaftPeerStub) -> None:
        for _ in range(20):
            with self._lock:
                if self._role != "leader":
                    return
                term = self._term
                next_index = self._next_index.get(peer_id, len(self._log) + 1)
                previous_index = next_index - 1
                previous_term = self._log[previous_index - 1]["term"] if previous_index else 0
                entries = self._log[next_index - 1:]
                request = raft_pb2.AppendEntriesRequest(
                    term=term,
                    leader_id=self.node_id,
                    previous_log_index=previous_index,
                    previous_log_term=previous_term,
                    leader_commit=self._commit_index,
                    entries=[
                        raft_pb2.LogEntry(
                            index=entry["index"],
                            term=entry["term"],
                            command_json=entry["command_json"],
                        )
                        for entry in entries
                    ],
                )
            try:
                response = stub.AppendEntries(request, timeout=self.rpc_timeout)
            except grpc.RpcError as error:
                logger.debug("Raft append from %s to %s failed: %s", self.node_id, peer_id, error)
                return
            with self._lock:
                if response.term > self._term:
                    self._become_follower_locked(response.term, None)
                    return
                if self._role != "leader" or self._term != term:
                    return
                if response.success:
                    match_index = previous_index + len(entries)
                    self._match_index[peer_id] = match_index
                    self._next_index[peer_id] = match_index + 1
                    return
                conflict = int(response.conflict_index)
                self._next_index[peer_id] = max(1, min(next_index - 1, conflict or next_index - 1))

    def _advance_commit_locked(self) -> None:
        for candidate in range(len(self._log), self._commit_index, -1):
            if self._log[candidate - 1]["term"] != self._term:
                continue
            replicated = 1 + sum(index >= candidate for index in self._match_index.values())
            if replicated >= self._majority:
                self._commit_index = candidate
                self._apply_committed_locked()
                self._persist_locked()
                break

    def _apply_committed_locked(self) -> None:
        while self._last_applied < self._commit_index:
            entry = self._log[self._last_applied]
            operation = json.loads(entry["command_json"])
            _apply_operation(self._application_state, operation)
            self._last_applied += 1

    def _become_follower_locked(self, term: int, leader_id: str | None) -> None:
        if term < self._term:
            return
        term_changed = term > self._term
        self._term = term
        self._role = "follower"
        self._leader_id = leader_id
        if term_changed:
            self._voted_for = None
        self._last_leader_contact = time.monotonic()
        self._reset_election_deadline_locked()
        self._persist_locked()

    def _last_log_position_locked(self) -> tuple[int, int]:
        if not self._log:
            return 0, 0
        return len(self._log), int(self._log[-1]["term"])

    @property
    def _majority(self) -> int:
        return (len(self.peer_targets) + 1) // 2 + 1

    def _reset_election_deadline_locked(self) -> None:
        self._election_deadline = time.monotonic() + random.uniform(*self.election_timeout)

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if payload.get("node_id") != self.node_id:
                raise RuntimeError(f"Raft state file belongs to another node: {self.state_path}")
            self._term = int(payload["term"])
            self._voted_for = payload.get("voted_for")
            self._log = payload["log"]
            self._commit_index = int(payload["commit_index"])
            self._last_applied = int(payload.get("last_applied", 0))
            self._application_state = payload.get("application_state", {"files": {}, "logs": []})
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            if isinstance(error, RuntimeError):
                raise
            raise RuntimeError(f"Could not load Raft state from {self.state_path}: {error}") from error

    def _persist_locked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "node_id": self.node_id,
            "term": self._term,
            "voted_for": self._voted_for,
            "log": self._log,
            "commit_index": self._commit_index,
            "last_applied": self._last_applied,
            "application_state": self._application_state,
        }
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as state_file:
            json.dump(payload, state_file, ensure_ascii=False, separators=(",", ":"))
            state_file.flush()
            os.fsync(state_file.fileno())
        os.replace(temporary, self.state_path)


class RaftPeerService(raft_pb2_grpc.RaftPeerServicer):
    def __init__(self, node: RaftNode) -> None:
        self.node = node

    def RequestVote(self, request, context):
        del context
        return self.node.request_vote(request)

    def AppendEntries(self, request, context):
        del context
        return self.node.append_entries(request)

    def Propose(self, request, context):
        del context
        return self.node.propose(request.operation_json)

    def GetStatus(self, request, context):
        del request, context
        status = self.node.status()
        return raft_pb2.NodeStatus(
            node_id=status["node_id"],
            role=status["role"],
            term=status["term"],
            leader_id=status["leader_id"],
            commit_index=status["commit_index"],
            last_applied=status["last_applied"],
            last_log_index=status["last_log_index"],
            last_log_term=status["last_log_term"],
            heartbeat_age_ms=status["heartbeat_age_ms"],
            recent_entries=[
                raft_pb2.LogEntry(
                    index=entry["index"],
                    term=entry["term"],
                    command_json=json.dumps(entry["command"], separators=(",", ":")),
                )
                for entry in status["recent_entries"]
            ],
        )


def start_raft_grpc_server(
    node: RaftNode,
    address: str,
    max_workers: int = 8,
) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    raft_pb2_grpc.add_RaftPeerServicer_to_server(RaftPeerService(node), server)
    bound_port = server.add_insecure_port(address)
    if bound_port == 0:
        node.close()
        raise RuntimeError(f"Could not bind Raft metadata node {node.node_id} to {address}.")
    server.start()
    return server

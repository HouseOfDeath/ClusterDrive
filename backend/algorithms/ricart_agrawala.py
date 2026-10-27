from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import threading
import time
from typing import Callable, Generator, TypedDict

from backend.algorithms.lamport import LamportClock

class ProtocolEvent(TypedDict):
    event: str
    node_id: str
    logical_clock: int
    description: str


EventLogger = Callable[[ProtocolEvent], None]


@dataclass
class _Node:
    node_id: str
    clock: LamportClock
    condition: threading.Condition = field(default_factory=threading.Condition)
    requesting: dict[str, tuple[int, str]] = field(default_factory=dict)
    in_critical: set[str] = field(default_factory=set)
    waiting_for: dict[str, set[str]] = field(default_factory=dict)
    deferred: dict[str, list[tuple[str, tuple[int, str]]]] = field(default_factory=dict)


class RicartAgrawalaCluster:
    """Ricart-Agrawala mutual exclusion across a fixed set of logical nodes.

    The nodes exchange protocol messages directly in this educational
    in-process cluster. The protocol state machine is independent of the API
    and can be tested with concurrent callers.
    """

    def __init__(
        self,
        node_ids: list[str],
        event_logger: EventLogger | None = None,
    ) -> None:
        if not node_ids or len(set(node_ids)) != len(node_ids):
            raise ValueError("Metadata node IDs must be non-empty and unique.")
        self._nodes = {
            node_id: _Node(node_id, LamportClock(node_id))
            for node_id in sorted(node_ids)
        }
        self._event_logger = event_logger
        self._events: list[ProtocolEvent] = []
        self._events_lock = threading.Lock()
        self._entry_counts: dict[str, int] = {}
        self._entry_counts_lock = threading.Lock()

    def _log(self, event: str, node_id: str, detail: str) -> ProtocolEvent:
        node = self._nodes[node_id]
        timestamp = node.clock.tick()
        record: ProtocolEvent = {
            "event": event,
            "node_id": node_id,
            "logical_clock": timestamp,
            "description": detail,
        }
        with self._events_lock:
            self._events = [*self._events[-199:], record]
        if self._event_logger is not None:
            self._event_logger(record)
        return record

    def acquire(self, node_id: str, resource: str, timeout: float | None = None) -> None:
        requester = self._get_node(node_id)
        if not resource:
            raise ValueError("A critical-section resource name is required.")
        with requester.condition:
            if resource in requester.requesting or resource in requester.in_critical:
                raise RuntimeError(f"{node_id} already requested {resource}.")
            request_timestamp = requester.clock.tick()
            priority = (request_timestamp, node_id)
            requester.requesting[resource] = priority
            peers = [peer for peer_id, peer in self._nodes.items() if peer_id != node_id]
            requester.waiting_for[resource] = {peer.node_id for peer in peers}
        self._log("lock_requested", node_id, f"Requested {resource} at {request_timestamp}.")

        for peer in peers:
            message_timestamp = requester.clock.send()
            self._log("request_sent", node_id, f"Sent request for {resource} to {peer.node_id}.")
            peer.clock.receive(message_timestamp)
            self._log("request_received", peer.node_id, f"Received request for {resource} from {node_id}.")
            grant_now = self._on_request(peer, node_id, resource, priority)
            if grant_now:
                self._send_permission(peer, requester, resource)

        deadline = None if timeout is None else time.monotonic() + timeout
        with requester.condition:
            while requester.waiting_for[resource]:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    del requester.waiting_for[resource]
                    del requester.requesting[resource]
                    requester.condition.notify_all()
                    raise TimeoutError(f"Timed out waiting for permission to enter {resource}.")
                requester.condition.wait(remaining)
            requester.in_critical.add(resource)
        self._log("lock_acquired", node_id, f"Entered critical section for {resource}.")
        with self._entry_counts_lock:
            self._entry_counts[resource] = self._entry_counts.get(resource, 0) + 1

    def release(self, node_id: str, resource: str) -> None:
        node = self._get_node(node_id)
        with node.condition:
            if resource not in node.in_critical:
                raise RuntimeError(f"{node_id} does not hold {resource}.")
            node.in_critical.remove(resource)
            node.requesting.pop(resource, None)
            deferred = node.deferred.pop(resource, [])
            node.clock.tick()
        self._log("lock_released", node_id, f"Released critical section for {resource}.")
        for requester_id, _ in deferred:
            requester = self._get_node(requester_id)
            self._send_permission(node, requester, resource)

    @contextmanager
    def critical_section(
        self,
        node_id: str,
        resource: str,
        timeout: float | None = None,
    ) -> Generator[None, None, None]:
        self.acquire(node_id, resource, timeout)
        try:
            yield
        finally:
            self.release(node_id, resource)

    def _on_request(
        self,
        node: _Node,
        requester_id: str,
        resource: str,
        incoming_priority: tuple[int, str],
    ) -> bool:
        with node.condition:
            own_priority = node.requesting.get(resource)
            defer = (
                resource in node.in_critical
                or own_priority is not None and own_priority < incoming_priority
            )
            if defer:
                node.deferred.setdefault(resource, []).append((requester_id, incoming_priority))
                self._log("permission_deferred", node.node_id, f"Deferred {requester_id} for {resource}.")
                return False
        self._log("permission_granted", node.node_id, f"Granted {requester_id} for {resource}.")
        return True

    def _send_permission(self, sender: _Node, requester: _Node, resource: str) -> None:
        message_timestamp = sender.clock.send()
        self._log("permission_sent", sender.node_id, f"Sent permission to {requester.node_id} for {resource}.")
        requester.clock.receive(message_timestamp)
        with requester.condition:
            waiting = requester.waiting_for.get(resource)
            if waiting is not None:
                waiting.discard(sender.node_id)
                requester.condition.notify_all()
        self._log("permission_received", requester.node_id, f"Received permission from {sender.node_id} for {resource}.")

    def snapshot(self) -> dict[str, object]:
        nodes = []
        for node in self._nodes.values():
            with node.condition:
                nodes.append({
                    "node_id": node.node_id,
                    "logical_clock": node.clock.value,
                    "requesting": sorted(node.requesting),
                    "in_critical_section": sorted(node.in_critical),
                    "deferred_requests": sum(len(items) for items in node.deferred.values()),
                })
        with self._events_lock, self._entry_counts_lock:
            return {
                "nodes": nodes,
                "critical_section_entries": dict(self._entry_counts),
                "recent_protocol_events": [dict(event) for event in self._events[-30:]],
            }

    def clock_tick(self, node_id: str) -> int:
        record = self._log("local_event", node_id, "Recorded a local metadata operation.")
        return record["logical_clock"]

    def _get_node(self, node_id: str) -> _Node:
        try:
            return self._nodes[node_id]
        except KeyError as error:
            raise ValueError(f"Unknown metadata node: {node_id}") from error

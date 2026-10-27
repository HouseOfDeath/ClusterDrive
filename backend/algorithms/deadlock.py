from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any


@dataclass
class _Transaction:
    transaction_id: str
    start_order: int
    state: str = "active"


class WaitForGraph:
    """Lock ownership and wait graph with youngest-transaction victim policy."""

    victim_policy = (
        "Abort the youngest active transaction in the detected cycle; "
        "ties break by greatest transaction ID."
    )

    def __init__(self) -> None:
        self._transactions: dict[str, _Transaction] = {}
        self._lock_owners: dict[str, str] = {}
        self._waiting_for: dict[str, str] = {}
        self._next_start_order = 0
        self._lock = threading.RLock()

    def begin(self, transaction_id: str) -> None:
        with self._lock:
            if transaction_id in self._transactions:
                raise ValueError(f"Transaction {transaction_id} already exists.")
            self._next_start_order += 1
            self._transactions[transaction_id] = _Transaction(transaction_id, self._next_start_order)

    def acquire(self, transaction_id: str, lock_id: str) -> bool:
        with self._lock:
            self._active_transaction(transaction_id)
            owner = self._lock_owners.get(lock_id)
            if owner is None or owner == transaction_id:
                self._lock_owners[lock_id] = transaction_id
                self._waiting_for.pop(transaction_id, None)
                return True
            self._waiting_for[transaction_id] = lock_id
            return False

    def graph(self) -> dict[str, list[str]]:
        with self._lock:
            return self._graph_unlocked()

    def detect_cycle(self) -> list[str] | None:
        with self._lock:
            return self._find_cycle(self._graph_unlocked())

    def recover(self) -> dict[str, Any]:
        with self._lock:
            before = self._graph_unlocked()
            cycle = self._find_cycle(before)
            if cycle is None:
                return {
                    "cycle_detected": False,
                    "cycle": [],
                    "victim": None,
                    "released_locks": [],
                    "graph_before": before,
                    "graph_after": before,
                    "lock_owners": dict(self._lock_owners),
                    "victim_policy": self.victim_policy,
                }
            victim = max(
                cycle,
                key=lambda transaction_id: (
                    self._transactions[transaction_id].start_order,
                    transaction_id,
                ),
            )
            self._transactions[victim].state = "aborted"
            self._waiting_for.pop(victim, None)
            released = sorted(
                lock_id
                for lock_id, owner in self._lock_owners.items()
                if owner == victim
            )
            for lock_id in released:
                del self._lock_owners[lock_id]
                self._grant_oldest_waiter(lock_id)
            after = self._graph_unlocked()
            return {
                "cycle_detected": True,
                "cycle": cycle,
                "victim": victim,
                "released_locks": released,
                "graph_before": before,
                "graph_after": after,
                "lock_owners": dict(self._lock_owners),
                "victim_policy": self.victim_policy,
            }

    def _active_transaction(self, transaction_id: str) -> _Transaction:
        transaction = self._transactions.get(transaction_id)
        if transaction is None or transaction.state != "active":
            raise ValueError(f"Transaction {transaction_id} is not active.")
        return transaction

    def _graph_unlocked(self) -> dict[str, list[str]]:
        graph = {
            transaction_id: []
            for transaction_id, transaction in self._transactions.items()
            if transaction.state == "active"
        }
        for waiter, lock_id in self._waiting_for.items():
            owner = self._lock_owners.get(lock_id)
            if owner is not None and waiter in graph and owner in graph:
                graph[waiter].append(owner)
        return {key: sorted(value) for key, value in sorted(graph.items())}

    @staticmethod
    def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
        visiting: set[str] = set()
        visited: set[str] = set()
        path: list[str] = []

        def visit(node: str) -> list[str] | None:
            if node in visiting:
                start = path.index(node)
                return path[start:] + [node]
            if node in visited:
                return None
            visiting.add(node)
            path.append(node)
            for neighbor in graph.get(node, []):
                cycle = visit(neighbor)
                if cycle is not None:
                    return cycle
            path.pop()
            visiting.remove(node)
            visited.add(node)
            return None

        for node in graph:
            cycle = visit(node)
            if cycle is not None:
                return cycle
        return None

    def _grant_oldest_waiter(self, lock_id: str) -> None:
        waiters = [
            transaction_id
            for transaction_id, waiting_lock in self._waiting_for.items()
            if waiting_lock == lock_id
            and self._transactions[transaction_id].state == "active"
        ]
        if not waiters:
            return
        winner = min(waiters, key=lambda transaction_id: (
            self._transactions[transaction_id].start_order,
            transaction_id,
        ))
        self._lock_owners[lock_id] = winner
        self._waiting_for.pop(winner, None)

from __future__ import annotations

import threading


class LamportClock:
    """Thread-safe Lamport counter belonging to one logical metadata node."""

    def __init__(self, node_id: str, initial_value: int = 0) -> None:
        if not node_id:
            raise ValueError("A Lamport clock requires a node ID.")
        if initial_value < 0:
            raise ValueError("A Lamport clock cannot start below zero.")
        self.node_id = node_id
        self._value = initial_value
        self._lock = threading.Lock()

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def tick(self) -> int:
        with self._lock:
            self._value += 1
            return self._value

    def send(self) -> int:
        """Advance before sending a message and return its timestamp."""
        return self.tick()

    def receive(self, message_timestamp: int) -> int:
        if message_timestamp < 0:
            raise ValueError("A received Lamport timestamp cannot be negative.")
        with self._lock:
            self._value = max(self._value, message_timestamp) + 1
            return self._value

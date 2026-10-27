from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time

from backend.algorithms.deadlock import WaitForGraph
from backend.algorithms.lamport import LamportClock
from backend.algorithms.ricart_agrawala import RicartAgrawalaCluster


def test_lamport_clock_ticks_sends_and_merges_received_timestamps() -> None:
    clock = LamportClock("metadata-01")

    assert clock.tick() == 1
    assert clock.send() == 2
    assert clock.receive(7) == 8
    assert clock.receive(3) == 9


def test_simultaneous_ricart_agrawala_requests_never_overlap() -> None:
    cluster = RicartAgrawalaCluster(["metadata-01", "metadata-02"])
    start = threading.Barrier(3)
    state_lock = threading.Lock()
    active_sections = 0
    maximum_concurrent_sections = 0

    def enter(node_id: str) -> None:
        nonlocal active_sections, maximum_concurrent_sections
        start.wait(timeout=2)
        with cluster.critical_section(node_id, "shared-file-metadata", timeout=2):
            with state_lock:
                active_sections += 1
                maximum_concurrent_sections = max(
                    maximum_concurrent_sections,
                    active_sections,
                )
            time.sleep(0.02)
            with state_lock:
                active_sections -= 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(enter, "metadata-01")
        second = executor.submit(enter, "metadata-02")
        start.wait(timeout=2)
        first.result(timeout=3)
        second.result(timeout=3)

    assert maximum_concurrent_sections == 1
    assert cluster.snapshot()["critical_section_entries"] == {
        "shared-file-metadata": 2,
    }


def test_ricart_agrawala_uses_node_id_to_break_equal_timestamp_ties() -> None:
    cluster = RicartAgrawalaCluster(["metadata-02", "metadata-01"])
    node_01 = cluster._get_node("metadata-01")
    node_02 = cluster._get_node("metadata-02")
    with node_01.condition:
        node_01.requesting["resource"] = (5, "metadata-01")

    assert cluster._on_request(node_01, "metadata-02", "resource", (5, "metadata-02")) is False

    with node_01.condition:
        assert node_01.deferred["resource"] == [
            ("metadata-02", (5, "metadata-02")),
        ]
    assert not node_02.requesting


def test_wait_for_graph_detects_cycle_aborts_youngest_and_releases_locks() -> None:
    graph = WaitForGraph()
    graph.begin("transaction-01")
    graph.begin("transaction-02")
    assert graph.acquire("transaction-01", "lock-A")
    assert graph.acquire("transaction-02", "lock-B")
    assert not graph.acquire("transaction-01", "lock-B")
    assert not graph.acquire("transaction-02", "lock-A")

    recovery = graph.recover()

    assert recovery["cycle_detected"] is True
    assert recovery["cycle"] == ["transaction-01", "transaction-02", "transaction-01"]
    assert recovery["victim"] == "transaction-02"
    assert recovery["released_locks"] == ["lock-B"]
    assert recovery["graph_after"] == {
        "transaction-01": [],
    }
    assert recovery["lock_owners"] == {
        "lock-A": "transaction-01",
        "lock-B": "transaction-01",
    }
    assert "youngest" in recovery["victim_policy"]


def test_wait_for_graph_returns_no_victim_without_a_cycle() -> None:
    graph = WaitForGraph()
    graph.begin("transaction-01")
    graph.begin("transaction-02")
    graph.acquire("transaction-01", "lock-A")
    assert not graph.acquire("transaction-02", "lock-A")

    recovery = graph.recover()

    assert recovery["cycle_detected"] is False
    assert recovery["victim"] is None
    assert recovery["graph_after"] == {"transaction-01": [], "transaction-02": ["transaction-01"]}

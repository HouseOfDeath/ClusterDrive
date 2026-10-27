from __future__ import annotations

import argparse
import logging
import os
import signal
import threading

from backend.metadata.config import (
    configured_metadata_peers,
    metadata_state_directory,
    raft_election_timeout_range,
    raft_heartbeat_interval_seconds,
    raft_rpc_timeout_seconds,
)
from backend.metadata.raft import RaftNode, start_raft_grpc_server

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one ClusterDrive educational Raft metadata node.")
    parser.add_argument("--node-id", required=True, help="Configured metadata node ID, for example metadata-01.")
    arguments = parser.parse_args()

    peers = configured_metadata_peers()
    configured = {peer.node_id: peer for peer in peers}
    node_config = configured.get(arguments.node_id)
    if node_config is None:
        parser.error(f"{arguments.node_id!r} is not present in CLUSTERDRIVE_METADATA_NODES.")
    bind_host = os.getenv("CLUSTERDRIVE_METADATA_BIND_HOST")
    bind_address = node_config.target
    if bind_host:
        _, separator, port = node_config.target.rpartition(":")
        if not separator or not port.isdigit():
            parser.error(f"Invalid metadata peer address: {node_config.target!r}.")
        bind_address = f"{bind_host}:{port}"
    peer_targets = {
        peer.node_id: peer.target
        for peer in peers
        if peer.node_id != arguments.node_id
    }
    state_path = metadata_state_directory(arguments.node_id) / "raft-state.json"
    node = RaftNode(
        arguments.node_id,
        peer_targets,
        state_path,
        election_timeout=raft_election_timeout_range(),
        heartbeat_interval=raft_heartbeat_interval_seconds(),
        rpc_timeout=raft_rpc_timeout_seconds(),
    )
    server = start_raft_grpc_server(node, bind_address)
    stopped = threading.Event()

    def stop_node(_signal_number: int, _frame: object) -> None:
        del _signal_number, _frame
        stopped.set()

    signal.signal(signal.SIGINT, stop_node)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_node)
    logger.info(
        "Started %s for peer address %s, listening on %s with persistent state %s",
        arguments.node_id,
        node_config.target,
        bind_address,
        state_path,
    )
    try:
        stopped.wait()
    finally:
        server.stop(grace=1).wait()
        node.close()
        logger.info("Stopped %s without deleting persistent state.", arguments.node_id)


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("CLUSTERDRIVE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    main()

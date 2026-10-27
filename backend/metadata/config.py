from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

from backend.app.config import PROJECT_ROOT

_NODE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


@dataclass(frozen=True)
class MetadataPeerConfig:
    node_id: str
    target: str


def configured_metadata_peers() -> list[MetadataPeerConfig]:
    definitions = os.getenv(
        "CLUSTERDRIVE_METADATA_NODES",
        "metadata-01=127.0.0.1:50161,"
        "metadata-02=127.0.0.1:50162,"
        "metadata-03=127.0.0.1:50163",
    )
    peers: list[MetadataPeerConfig] = []
    seen_ids: set[str] = set()
    seen_targets: set[str] = set()
    for definition in definitions.split(","):
        entry = definition.strip()
        if not entry:
            continue
        node_id, separator, target = entry.partition("=")
        node_id = node_id.strip()
        target = target.strip()
        if not separator or not node_id or not target:
            raise ValueError(
                "CLUSTERDRIVE_METADATA_NODES entries must use node-id=host:port."
            )
        if _NODE_ID_PATTERN.fullmatch(node_id) is None:
            raise ValueError(f"Invalid metadata node ID {node_id!r}; use letters, digits, '_' or '-'.")
        if node_id in seen_ids:
            raise ValueError(f"Duplicate metadata node ID: {node_id}")
        if target in seen_targets:
            raise ValueError(f"Duplicate metadata node address: {target}")
        seen_ids.add(node_id)
        seen_targets.add(target)
        peers.append(MetadataPeerConfig(node_id, target))
    if len(peers) != 3:
        raise ValueError("The educational Raft cluster requires exactly three metadata nodes.")
    return peers


def metadata_state_directory(node_id: str) -> Path:
    configured = Path(os.getenv("CLUSTERDRIVE_METADATA_STATE_DIR", "./data/metadata-nodes"))
    base = configured if configured.is_absolute() else PROJECT_ROOT / configured
    return base / node_id


def metadata_rpc_timeout_seconds() -> float:
    value = float(os.getenv("CLUSTERDRIVE_METADATA_RPC_TIMEOUT_SECONDS", "1.0"))
    if value <= 0:
        raise ValueError("CLUSTERDRIVE_METADATA_RPC_TIMEOUT_SECONDS must be positive.")
    return value


def raft_heartbeat_interval_seconds() -> float:
    value = float(os.getenv("CLUSTERDRIVE_RAFT_HEARTBEAT_INTERVAL_SECONDS", "0.25"))
    if value <= 0:
        raise ValueError("CLUSTERDRIVE_RAFT_HEARTBEAT_INTERVAL_SECONDS must be positive.")
    return value


def raft_election_timeout_range() -> tuple[float, float]:
    minimum = float(os.getenv("CLUSTERDRIVE_RAFT_ELECTION_TIMEOUT_MIN_SECONDS", "1.5"))
    maximum = float(os.getenv("CLUSTERDRIVE_RAFT_ELECTION_TIMEOUT_MAX_SECONDS", "2.5"))
    if minimum <= 0 or maximum <= minimum:
        raise ValueError("Raft election timeout maximum must be greater than a positive minimum.")
    return minimum, maximum


def raft_rpc_timeout_seconds() -> float:
    value = float(os.getenv("CLUSTERDRIVE_RAFT_RPC_TIMEOUT_SECONDS", "0.75"))
    if value <= 0:
        raise ValueError("CLUSTERDRIVE_RAFT_RPC_TIMEOUT_SECONDS must be positive.")
    return value

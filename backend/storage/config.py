from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from backend.app.config import PROJECT_ROOT


@dataclass(frozen=True)
class StorageNodeConfig:
    node_id: str
    target: str
    storage_directory: Path


def configured_storage_nodes() -> list[StorageNodeConfig]:
    definitions = os.getenv(
        "CLUSTERDRIVE_STORAGE_NODES",
        "node-01=127.0.0.1:50051,"
        "node-02=127.0.0.1:50052,"
        "node-03=127.0.0.1:50053",
    )
    nodes: list[StorageNodeConfig] = []
    seen_ids: set[str] = set()
    for definition in definitions.split(","):
        entry = definition.strip()
        if not entry:
            continue
        node_id, separator, target = entry.partition("=")
        node_id = node_id.strip()
        target = target.strip()
        if not separator or not node_id or not target:
            raise ValueError(
                "CLUSTERDRIVE_STORAGE_NODES entries must use node-id=host:port."
            )
        if node_id in seen_ids:
            raise ValueError(f"Duplicate storage node ID: {node_id}")
        seen_ids.add(node_id)
        directory = PROJECT_ROOT / "data" / "storage" / node_id
        nodes.append(StorageNodeConfig(node_id, target, directory))
    return nodes


def metadata_path() -> Path:
    configured = os.getenv("CLUSTERDRIVE_METADATA_PATH", "./data/metadata.json")
    path = Path(configured)
    return path if path.is_absolute() else PROJECT_ROOT / path


def chunk_size_bytes() -> int:
    value = int(os.getenv("CLUSTERDRIVE_CHUNK_SIZE_BYTES", str(1024 * 1024)))
    if value < 1:
        raise ValueError("CLUSTERDRIVE_CHUNK_SIZE_BYTES must be greater than zero.")
    return value


def replication_factor() -> int:
    value = int(os.getenv("CLUSTERDRIVE_REPLICATION_FACTOR", "2"))
    if value < 1:
        raise ValueError("CLUSTERDRIVE_REPLICATION_FACTOR must be greater than zero.")
    return value


def storage_rpc_timeout_seconds() -> float:
    value = float(os.getenv("CLUSTERDRIVE_STORAGE_RPC_TIMEOUT_SECONDS", "5.0"))
    if value <= 0:
        raise ValueError("CLUSTERDRIVE_STORAGE_RPC_TIMEOUT_SECONDS must be positive.")
    return value


def redis_url() -> str:
    return os.getenv("CLUSTERDRIVE_REDIS_URL", "redis://127.0.0.1:6379/0")


def metadata_cache_ttl_seconds() -> int:
    value = int(os.getenv("CLUSTERDRIVE_METADATA_CACHE_TTL_SECONDS", "60"))
    if value < 1:
        raise ValueError("CLUSTERDRIVE_METADATA_CACHE_TTL_SECONDS must be greater than zero.")
    return value

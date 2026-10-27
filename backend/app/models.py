from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    service: str = "clusterdive-api"
    version: str = "0.2.0"


class FeatureStatus(ApiModel):
    status: Literal["implemented", "not_implemented", "unavailable"]
    message: str


class DashboardResponse(ApiModel):
    storage_used_bytes: int = Field(default=0, ge=0)
    storage_capacity_bytes: int = Field(default=0, ge=0)
    total_files: int = Field(default=0, ge=0)
    active_nodes: int = Field(default=0, ge=0)
    total_nodes: int = Field(default=0, ge=0)
    cache_hit_rate: float | None = Field(default=None, ge=0, le=100)
    cache_hits: int = Field(default=0, ge=0)
    cache_misses: int = Field(default=0, ge=0)
    cache_errors: int = Field(default=0, ge=0)
    cache_available: bool | None = None
    cache_ttl_seconds: int = Field(default=60, ge=1)
    features: dict[str, FeatureStatus]


class FileRecord(ApiModel):
    id: str
    name: str
    size_bytes: int = Field(ge=0)
    content_type: str | None = None
    created_at: str | None = None
    replica_count: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    replication_degraded: bool = False
    replication_status: Literal["pending", "synchronized", "failed", "degraded"] = "synchronized"


class FilesResponse(ApiModel):
    items: list[FileRecord]
    count: int = Field(ge=0)


class StorageNodeRecord(ApiModel):
    id: str
    name: str
    status: Literal["healthy", "unavailable"]
    location: str | None = None
    storage_used_bytes: int = Field(default=0, ge=0)
    storage_capacity_bytes: int = Field(default=0, ge=0)
    file_count: int = Field(default=0, ge=0)
    error: str | None = None


class NodesResponse(ApiModel):
    items: list[StorageNodeRecord]
    count: int = Field(ge=0)
    active_count: int = Field(ge=0)


class ActivityLogRecord(ApiModel):
    id: str
    timestamp: str
    event: str
    description: str
    status: Literal["info", "success", "warning", "error"]
    logical_clock: int | None = Field(default=None, ge=0)
    node_id: str | None = None


class LogsResponse(ApiModel):
    items: list[ActivityLogRecord]
    count: int = Field(ge=0)


class MetadataNodeClock(ApiModel):
    node_id: str
    logical_clock: int = Field(ge=0)
    requesting: list[str]
    in_critical_section: list[str]
    deferred_requests: int = Field(ge=0)


class AlgorithmStatusResponse(ApiModel):
    nodes: list[MetadataNodeClock]
    critical_section_entries: dict[str, int]
    recent_protocol_events: list[dict[str, str | int]]
    last_deadlock_demo: dict[str, object] | None = None


class DeadlockDemoResponse(ApiModel):
    execution_id: str
    cycle_detected: bool
    cycle: list[str]
    victim: str | None
    released_locks: list[str]
    graph_before: dict[str, list[str]]
    graph_after: dict[str, list[str]]
    lock_owners: dict[str, str]
    victim_policy: str
    logical_clock: int = Field(ge=0)
    node_id: str


class ReplicaRecord(ApiModel):
    node_id: str
    status: Literal["pending", "synchronized", "failed"]
    version: int = Field(ge=0)
    target_version: int = Field(ge=1)
    error: str | None = None


class ChunkReplicationRecord(ApiModel):
    index: int = Field(ge=0)
    chunk_id: str
    replicas: list[ReplicaRecord]


class FileReplicationRecord(ApiModel):
    file_id: str
    name: str
    status: Literal["pending", "synchronized", "failed", "degraded"]
    chunks: list[ChunkReplicationRecord]


class ReplicationStatusResponse(ApiModel):
    target_replicas: int = Field(ge=1)
    pending: int = Field(ge=0)
    synchronized: int = Field(ge=0)
    failed: int = Field(ge=0)
    files: list[FileReplicationRecord]
    demo: dict[str, object] | None = None


class ReplicationDemoResponse(ApiModel):
    status: Literal["pending", "synchronized", "failed"]
    chunk_id: str
    version: int = Field(ge=1)
    source_node: str
    target_node: str
    source_status: Literal["pending", "synchronized", "failed"]
    target_status: Literal["pending", "synchronized", "failed"]
    source_version: int = Field(ge=0)
    target_version: int = Field(ge=0)
    error: str | None = None


class ClusterMetricsResponse(ApiModel):
    cache_hits: int = Field(ge=0)
    cache_misses: int = Field(ge=0)
    cache_errors: int = Field(ge=0)
    cache_hit_rate: float | None = Field(default=None, ge=0, le=100)
    cache_available: bool | None = None
    cache_ttl_seconds: int = Field(ge=1)
    placement_strategy: str
    placement_counts: dict[str, int]
    request_counts: dict[str, dict[str, int]]
    active_nodes: int = Field(ge=0)
    total_nodes: int = Field(ge=0)


class RaftLogEntry(ApiModel):
    index: int = Field(ge=1)
    term: int = Field(ge=1)
    command: dict[str, Any]
    committed: bool


class RaftMetadataNode(ApiModel):
    node_id: str
    address: str
    reachable: bool
    role: Literal["follower", "candidate", "leader", "unavailable"]
    term: int = Field(ge=0)
    leader_id: str
    commit_index: int = Field(ge=0)
    last_applied: int = Field(ge=0)
    last_log_index: int = Field(ge=0)
    last_log_term: int = Field(ge=0)
    heartbeat_age_ms: int | None = Field(default=None, ge=0)
    heartbeat_state: Literal["leader", "recent", "stale", "unavailable"]
    recent_entries: list[RaftLogEntry]
    error: str | None = None


class RaftClusterStatusResponse(ApiModel):
    node_count: int = Field(ge=1)
    reachable_nodes: int = Field(ge=0)
    quorum_required: int = Field(ge=1)
    quorum_available: bool
    leader_id: str
    nodes: list[RaftMetadataNode]
    recent_entries: list[RaftLogEntry]
    implementation: Literal["educational-raft"]

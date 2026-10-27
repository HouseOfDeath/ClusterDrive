from backend.app.models import FeatureStatus

INITIAL_FEATURES = {
    "file_upload": FeatureStatus(
        status="implemented",
        message="File upload, chunking, and checksums are available through the API.",
    ),
    "distributed_storage": FeatureStatus(
        status="implemented",
        message="Storage nodes use the generated gRPC service and separate data directories.",
    ),
    "replication": FeatureStatus(
        status="implemented",
        message="Primary chunks are accepted first; secondary replicas synchronize asynchronously and expose their real version and status.",
    ),
    "raft": FeatureStatus(
        status="unavailable",
        message="The educational Raft implementation is configured, but metadata peers are not currently available.",
    ),
    "redis_cache": FeatureStatus(
        status="implemented",
        message="File metadata uses Redis cache-aside reads, a configurable TTL, cache metrics, invalidation, and logged catalog fallback.",
    ),
    "lamport_clocks": FeatureStatus(
        status="implemented",
        message="Each logical metadata node maintains a Lamport clock; operation logs include node IDs and timestamps.",
    ),
    "distributed_locking": FeatureStatus(
        status="implemented",
        message="File metadata writes coordinate entry with Ricart–Agrawala permission messages and deterministic timestamp/node-ID ordering.",
    ),
    "deadlock_detection": FeatureStatus(
        status="implemented",
        message="The controlled wait-for-graph demo detects cycles and aborts the youngest transaction to release its locks.",
    ),
    "load_balancing": FeatureStatus(
        status="implemented",
        message="Health-checked round-robin primary placement spreads chunk writes across healthy nodes and reports per-node placement and request counts.",
    ),
    "checksum_verification": FeatureStatus(
        status="implemented",
        message="SHA-256 checksums are verified on storage writes and file reconstruction.",
    ),
}

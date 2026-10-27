from __future__ import annotations

import argparse
from concurrent import futures
import hashlib
import os
from pathlib import Path
import re
import threading

import grpc

from backend.app.config import PROJECT_ROOT
from backend.storage.proto import storage_pb2, storage_pb2_grpc

_CHUNK_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class StorageNode(storage_pb2_grpc.StorageServiceServicer):
    def __init__(
        self,
        node_id: str,
        storage_directory: Path,
        capacity_bytes: int = 0,
    ) -> None:
        if capacity_bytes < 0:
            raise ValueError("Storage capacity must not be negative.")
        self.node_id = node_id
        self.storage_directory = storage_directory.resolve()
        self.capacity_bytes = capacity_bytes
        self.storage_directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def UploadChunk(self, request, context):
        path = self._chunk_path(request.chunk_id, context)
        checksum = hashlib.sha256(request.data).hexdigest()
        if checksum != request.sha256:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Chunk SHA-256 checksum does not match.")
        with self._lock:
            current_size = self._storage_used_bytes()
            previous_size = path.stat().st_size if path.exists() else 0
            resulting_size = current_size - previous_size + len(request.data)
            if self.capacity_bytes and resulting_size > self.capacity_bytes:
                context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "Storage node capacity would be exceeded.")
            temporary_path = path.with_suffix(".tmp")
            try:
                temporary_path.write_bytes(request.data)
                os.replace(temporary_path, path)
            finally:
                temporary_path.unlink(missing_ok=True)
        return storage_pb2.UploadChunkResponse(
            chunk_id=request.chunk_id,
            sha256=checksum,
            size_bytes=len(request.data),
        )

    def DownloadChunk(self, request, context):
        path = self._chunk_path(request.chunk_id, context)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            context.abort(grpc.StatusCode.NOT_FOUND, f"Chunk {request.chunk_id} was not found.")
        return storage_pb2.DownloadChunkResponse(
            chunk_id=request.chunk_id,
            data=data,
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def DeleteChunk(self, request, context):
        path = self._chunk_path(request.chunk_id, context)
        with self._lock:
            existed = path.exists()
            path.unlink(missing_ok=True)
        return storage_pb2.DeleteChunkResponse(
            chunk_id=request.chunk_id,
            deleted=existed,
        )

    def CheckHealth(self, request, context):
        with self._lock:
            chunks = list(self.storage_directory.glob("*.chunk"))
            used_bytes = sum(path.stat().st_size for path in chunks if path.is_file())
        return storage_pb2.HealthResponse(
            node_id=self.node_id,
            status="healthy",
            storage_used_bytes=used_bytes,
            storage_capacity_bytes=self.capacity_bytes,
            stored_chunks=len(chunks),
        )

    def _storage_used_bytes(self) -> int:
        return sum(
            path.stat().st_size
            for path in self.storage_directory.glob("*.chunk")
            if path.is_file()
        )

    def _chunk_path(self, chunk_id: str, context) -> Path:
        if not _CHUNK_ID_PATTERN.fullmatch(chunk_id):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid chunk ID.")
        return self.storage_directory / f"{chunk_id}.chunk"


def serve_node(
    node_id: str,
    port: int,
    storage_directory: Path,
    capacity_bytes: int = 0,
) -> grpc.Server:
    if not 0 < port < 65536:
        raise ValueError("Port must be between 1 and 65535.")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    storage_pb2_grpc.add_StorageServiceServicer_to_server(
        StorageNode(node_id, storage_directory, capacity_bytes),
        server,
    )
    bound_port = server.add_insecure_port(f"0.0.0.0:{port}")
    if bound_port == 0:
        raise RuntimeError(f"Could not bind storage node {node_id} to port {port}.")
    server.start()
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a ClusterDrive gRPC storage node.")
    parser.add_argument("--node-id", default=os.getenv("CLUSTERDRIVE_NODE_ID", "node-01"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CLUSTERDRIVE_NODE_PORT", "50051")))
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path(
            os.getenv(
                "CLUSTERDRIVE_NODE_STORAGE_DIR",
                str(PROJECT_ROOT / "data" / "storage" / os.getenv("CLUSTERDRIVE_NODE_ID", "node-01")),
            )
        ),
    )
    parser.add_argument(
        "--capacity-bytes",
        type=int,
        default=int(os.getenv("CLUSTERDRIVE_NODE_CAPACITY_BYTES", "0")),
        help="Maximum storage in bytes; zero means unlimited.",
    )
    args = parser.parse_args()
    server = serve_node(args.node_id, args.port, args.storage_dir, args.capacity_bytes)
    print(
        f"Storage node {args.node_id} listening on port {args.port}; "
        f"data directory: {args.storage_dir.resolve()}",
        flush=True,
    )
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=2).wait()


if __name__ == "__main__":
    main()

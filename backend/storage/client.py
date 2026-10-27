from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable

import grpc

from backend.storage.config import StorageNodeConfig
from backend.storage.proto import storage_pb2, storage_pb2_grpc


class StorageRpcError(RuntimeError):
    def __init__(self, node_id: str, operation: str, message: str) -> None:
        self.node_id = node_id
        self.operation = operation
        super().__init__(f"{node_id} {operation} failed: {message}")


@dataclass(frozen=True)
class HealthyNode:
    node_id: str
    target: str
    storage_used_bytes: int
    storage_capacity_bytes: int
    stored_chunks: int


class StorageNodeClient:
    def __init__(self, config: StorageNodeConfig, timeout_seconds: float = 1.5) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.channel = grpc.insecure_channel(config.target)
        self.stub = storage_pb2_grpc.StorageServiceStub(self.channel)

    def check_health(self) -> HealthyNode:
        try:
            response = self.stub.CheckHealth(
                storage_pb2.HealthRequest(),
                timeout=self.timeout_seconds,
            )
        except grpc.RpcError as error:
            raise StorageRpcError(self.config.node_id, "health check", error.details() or str(error)) from error
        if response.status != "healthy":
            raise StorageRpcError(self.config.node_id, "health check", f"node reports {response.status}.")
        return HealthyNode(
            node_id=self.config.node_id,
            target=self.config.target,
            storage_used_bytes=response.storage_used_bytes,
            storage_capacity_bytes=response.storage_capacity_bytes,
            stored_chunks=response.stored_chunks,
        )

    def upload_chunk(self, chunk_id: str, data: bytes, checksum: str) -> int:
        try:
            response = self.stub.UploadChunk(
                storage_pb2.UploadChunkRequest(
                    chunk_id=chunk_id,
                    data=data,
                    sha256=checksum,
                ),
                timeout=self.timeout_seconds,
            )
        except grpc.RpcError as error:
            raise StorageRpcError(self.config.node_id, "upload", error.details() or str(error)) from error
        if response.sha256 != checksum or response.size_bytes != len(data):
            raise StorageRpcError(self.config.node_id, "upload", "node returned an invalid chunk receipt.")
        return response.size_bytes

    def download_chunk(self, chunk_id: str) -> tuple[bytes, str]:
        try:
            response = self.stub.DownloadChunk(
                storage_pb2.DownloadChunkRequest(chunk_id=chunk_id),
                timeout=self.timeout_seconds,
            )
        except grpc.RpcError as error:
            raise StorageRpcError(self.config.node_id, "download", error.details() or str(error)) from error
        return response.data, response.sha256

    def delete_chunk(self, chunk_id: str) -> None:
        try:
            self.stub.DeleteChunk(
                storage_pb2.DeleteChunkRequest(chunk_id=chunk_id),
                timeout=self.timeout_seconds,
            )
        except grpc.RpcError as error:
            raise StorageRpcError(self.config.node_id, "delete", error.details() or str(error)) from error

    def close(self) -> None:
        self.channel.close()


def order_nodes(nodes: Iterable[StorageNodeClient], chunk_index: int) -> list[StorageNodeClient]:
    ordered = sorted(nodes, key=lambda node: node.config.node_id)
    if not ordered:
        return []
    offset = chunk_index % len(ordered)
    return ordered[offset:] + ordered[:offset]


def checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

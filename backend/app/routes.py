from urllib.parse import quote

from fastapi import APIRouter, File, Request, Response, UploadFile, status

from backend.app.models import (
    AlgorithmStatusResponse,
    DashboardResponse,
    DeadlockDemoResponse,
    FileRecord,
    FilesResponse,
    HealthResponse,
    LogsResponse,
    NodesResponse,
    ClusterMetricsResponse,
    ReplicationDemoResponse,
    ReplicationStatusResponse,
    RaftClusterStatusResponse,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
def get_health() -> HealthResponse:
    return HealthResponse()


@router.get("/api/dashboard", response_model=DashboardResponse, tags=["dashboard"])
def get_dashboard(request: Request) -> DashboardResponse:
    service = request.app.state.storage_service
    return DashboardResponse(**service.dashboard())


@router.get("/api/files", response_model=FilesResponse, tags=["files"])
def get_files(request: Request) -> FilesResponse:
    items = request.app.state.storage_service.list_files()
    return FilesResponse(items=items, count=len(items))


@router.get("/api/nodes", response_model=NodesResponse, tags=["nodes"])
def get_nodes(request: Request) -> NodesResponse:
    items = request.app.state.storage_service.node_records()
    return NodesResponse(
        items=items,
        count=len(items),
        active_count=sum(node["status"] == "healthy" for node in items),
    )


@router.get("/api/logs", response_model=LogsResponse, tags=["logs"])
def get_logs(request: Request) -> LogsResponse:
    items = request.app.state.storage_service.catalog.list_logs()
    return LogsResponse(items=items, count=len(items))


@router.get(
    "/api/algorithms/status",
    response_model=AlgorithmStatusResponse,
    tags=["distributed algorithms"],
)
def get_algorithm_status(request: Request) -> AlgorithmStatusResponse:
    return AlgorithmStatusResponse(**request.app.state.storage_service.algorithm_status())


@router.post(
    "/api/algorithms/deadlock-demo",
    response_model=DeadlockDemoResponse,
    tags=["distributed algorithms"],
)
def run_deadlock_demo(request: Request) -> DeadlockDemoResponse:
    result = request.app.state.storage_service.run_deadlock_demo()
    return DeadlockDemoResponse(**result)


@router.get(
    "/api/replication/status",
    response_model=ReplicationStatusResponse,
    tags=["replication"],
)
def get_replication_status(request: Request) -> ReplicationStatusResponse:
    return ReplicationStatusResponse(**request.app.state.storage_service.replication_status())


@router.post(
    "/api/replication/demo",
    response_model=ReplicationDemoResponse,
    tags=["replication"],
)
def start_replication_demo(request: Request) -> ReplicationDemoResponse:
    result = request.app.state.storage_service.start_replication_demo()
    return ReplicationDemoResponse(**result)


@router.post(
    "/api/replication/demo/converge",
    response_model=ReplicationDemoResponse,
    tags=["replication"],
)
def converge_replication_demo(request: Request) -> ReplicationDemoResponse:
    result = request.app.state.storage_service.converge_replication_demo()
    return ReplicationDemoResponse(**result)


@router.get(
    "/api/metrics",
    response_model=ClusterMetricsResponse,
    tags=["metrics"],
)
def get_cluster_metrics(request: Request) -> ClusterMetricsResponse:
    return ClusterMetricsResponse(**request.app.state.storage_service.cluster_metrics())


@router.get(
    "/api/raft/status",
    response_model=RaftClusterStatusResponse,
    tags=["metadata consensus"],
)
def get_raft_status(request: Request) -> RaftClusterStatusResponse:
    return RaftClusterStatusResponse(**request.app.state.storage_service.raft_status())


@router.post(
    "/api/files",
    response_model=FileRecord,
    status_code=status.HTTP_201_CREATED,
    tags=["files"],
)
def upload_file(request: Request, file: UploadFile = File(...)) -> FileRecord:
    record = request.app.state.storage_service.upload_file(file)
    return FileRecord(**record)


@router.get("/api/files/{file_id}/download", tags=["files"])
def download_file(file_id: str, request: Request) -> Response:
    data, record = request.app.state.storage_service.download_file(file_id)
    filename = quote(record["name"], safe="")
    return Response(
        content=data,
        media_type=record.get("content_type") or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.delete("/api/files/{file_id}", response_model=FileRecord, tags=["files"])
def delete_file(file_id: str, request: Request) -> FileRecord:
    record = request.app.state.storage_service.delete_file(file_id)
    return FileRecord(**record)

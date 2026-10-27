from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_cors_origins
from backend.app.routes import router
from backend.app.storage_service import ClusterStorageService


def create_app(storage_service: ClusterStorageService | None = None) -> FastAPI:
    service = storage_service or ClusterStorageService()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.storage_service = service
        yield
        service.close()

    application = FastAPI(
        title="ClusterDrive API",
        description=(
            "File storage uses gRPC storage nodes; metadata writes are committed "
            "through a separate educational three-node Raft cluster."
        ),
        version="0.2.0",
        lifespan=lifespan,
    )
    application.state.storage_service = service
    application.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application


app = create_app()

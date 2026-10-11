"""Local data backup endpoints."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from zhiyu.application.data_archive import DataArchiveService


def build_data_router(service: DataArchiveService) -> APIRouter:
    router = APIRouter()

    @router.post("/api/data/backup")
    async def create_backup():
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(prefix="xingqi-backup-", suffix=".zip", delete=False) as file:
                temporary_path = Path(file.name)
            temporary_path.unlink()
            service.create(temporary_path)
            return FileResponse(
                temporary_path,
                media_type="application/zip",
                filename="xingqi-backup.zip",
                background=BackgroundTask(temporary_path.unlink, missing_ok=True),
            )
        except ValueError as exc:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from exc
        except Exception:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
            raise

    return router

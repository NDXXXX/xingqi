"""受管渠道媒体：下载、持久化、解析和限额清理。"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from zhiyu.infrastructure.config.settings import settings
from zhiyu.infrastructure.database.models import ChannelEvent, utcnow
from zhiyu.infrastructure.database.repositories.channel_repository import (
    ChannelMediaRepository,
)

from .messages import AudioPart, FilePart, ImagePart, InboundEvent


MEDIA_LIMITS = {"image": 20 * 1024**2, "audio": 50 * 1024**2, "file": 100 * 1024**2}
MEDIA_RETENTION_DAYS = 7
MEDIA_TOTAL_LIMIT = 1024**3


class MediaStore:
    def __init__(self, session_factory, root: Path | None = None) -> None:
        self.session_factory = session_factory
        self.root = root or settings.data_dir / "media"
        self.assets = ChannelMediaRepository()

    async def materialize_event(self, event: InboundEvent) -> InboundEvent:
        parts = []
        for part in event.parts:
            kind = part.type
            if kind not in MEDIA_LIMITS or part.source.startswith("managed://"):
                parts.append(part)
                continue
            try:
                source = await self.import_source(
                    part.source,
                    kind=kind,
                    channel_config_id=event.channel_config_id,
                    source_event_id=event.event_id,
                    mime_hint=part.mime_type,
                )
            except (ValueError, httpx.HTTPError):
                parts.append(type(part)(**{**part.model_dump(), "source": "unavailable://media"}))
            else:
                parts.append(type(part)(**{**part.model_dump(), "source": source}))
        event.parts = parts
        return event

    async def import_source(
        self,
        source: str,
        *,
        kind: str,
        channel_config_id: str | None,
        source_event_id: str | None,
        mime_hint: str | None = None,
    ) -> str:
        parsed = urlsplit(source)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("媒体来源必须是不含凭据的 HTTP(S) URL")
        limit = MEDIA_LIMITS[kind]
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, trust_env=False) as client:
            async with client.stream("GET", source) as response:
                response.raise_for_status()
                length = response.headers.get("content-length")
                if length and int(length) > limit:
                    raise ValueError("媒体超过大小限制")
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > limit:
                        raise ValueError("媒体超过大小限制")
                mime_type = (response.headers.get("content-type") or mime_hint or "").split(";", 1)[0]
        mime_type = self._validated_mime(kind, bytes(chunks), mime_type)
        digest = hashlib.sha256(chunks).hexdigest()
        suffix = mimetypes.guess_extension(mime_type) or ".bin"
        asset_id = str(uuid4())
        relative = Path(channel_config_id or "unscoped") / f"{asset_id}{suffix}"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(chunks)
        temporary.replace(destination)
        now = utcnow()
        with self.session_factory() as db:
            asset = self.assets.create(
                db,
                id=asset_id,
                channel_config_id=channel_config_id,
                source_event_id=source_event_id,
                relative_path=str(relative),
                mime_type=mime_type,
                size_bytes=len(chunks),
                sha256=digest,
                created_at=now,
                last_accessed_at=now,
                expires_at=now + timedelta(days=MEDIA_RETENTION_DAYS),
            )
        return f"managed://{asset.id}"

    def data_url(self, source: str) -> str | None:
        asset_id = source.removeprefix("managed://") if source.startswith("managed://") else ""
        if not asset_id:
            return None
        with self.session_factory() as db:
            asset = self.assets.get(db, asset_id)
            if asset is None:
                return None
            path = (self.root / asset.relative_path).resolve()
            if self.root.resolve() not in path.parents or not path.is_file():
                return None
            data = path.read_bytes()
            asset.last_accessed_at = utcnow()
            db.commit()
            return f"data:{asset.mime_type};base64,{base64.b64encode(data).decode()}"

    def local_path(self, source: str) -> Path | None:
        asset_id = source.removeprefix("managed://") if source.startswith("managed://") else ""
        if not asset_id:
            return None
        with self.session_factory() as db:
            asset = self.assets.get(db, asset_id)
            if asset is None:
                return None
            path = (self.root / asset.relative_path).resolve()
            return path if self.root.resolve() in path.parents and path.is_file() else None

    def onebot_source(self, source: str) -> str:
        path = self.local_path(source)
        if path is None:
            return source
        return "base64://" + base64.b64encode(path.read_bytes()).decode()

    def cleanup(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.session_factory() as db:
            candidates = self.assets.list_cleanup_candidates(db)
            total = sum(item.size_bytes for item in candidates)
            removed = 0
            now = utcnow()
            for asset in candidates:
                if asset.source_event_id:
                    event = db.get(ChannelEvent, asset.source_event_id)
                    if event is not None and event.status in {"pending", "processing", "responded"}:
                        continue
                if asset.expires_at > now and total <= MEDIA_TOTAL_LIMIT:
                    continue
                path = (self.root / asset.relative_path).resolve()
                if self.root.resolve() in path.parents:
                    path.unlink(missing_ok=True)
                total -= asset.size_bytes
                db.delete(asset)
                removed += 1
            db.commit()
            return removed

    @staticmethod
    def _validated_mime(kind: str, data: bytes, declared: str) -> str:
        if kind == "image":
            signatures = {
                b"\x89PNG\r\n\x1a\n": "image/png",
                b"\xff\xd8\xff": "image/jpeg",
                b"GIF87a": "image/gif",
                b"GIF89a": "image/gif",
                b"RIFF": "image/webp" if data[8:12] == b"WEBP" else "",
            }
            detected = next((mime for magic, mime in signatures.items() if mime and data.startswith(magic)), None)
            if detected is None:
                raise ValueError("图片文件头不受支持")
            return detected
        if kind == "audio" and declared and not declared.startswith("audio/"):
            raise ValueError("语音 MIME 类型无效")
        return declared or ("audio/octet-stream" if kind == "audio" else "application/octet-stream")

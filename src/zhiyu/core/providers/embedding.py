"""OpenAI-compatible embedding 客户端与向量存储。

配置存于 app_settings(key="embedding")：{"base_url", "model", "api_key_ref"}。
api_key_ref 遵循 Provider 约定：`env:NAME` 或 keyring 引用。
所有调用都是 best-effort：未配置或失败时返回 None / 不存储，检索降级为词法匹配。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiyu.infrastructure.config.keystore import keystore
from zhiyu.infrastructure.database.models import MemoryEmbedding
from zhiyu.infrastructure.database.repositories.setting_repository import SettingRepository

EMBEDDING_KEY = "embedding"


@dataclass
class EmbeddingConfig:
    base_url: str
    model: str
    api_key_ref: str | None = None


def load_config(db: Session) -> EmbeddingConfig | None:
    data = SettingRepository().get(db, EMBEDDING_KEY) or {}
    base_url = data.get("base_url")
    model = data.get("model")
    if not base_url or not model:
        return None
    return EmbeddingConfig(
        base_url=base_url, model=model, api_key_ref=data.get("api_key_ref")
    )


def save_config(db: Session, *, base_url: str, model: str, api_key_ref: str | None) -> None:
    SettingRepository().set(
        db,
        EMBEDDING_KEY,
        {"base_url": base_url, "model": model, "api_key_ref": api_key_ref},
    )


def resolve_api_key(ref: str | None) -> str | None:
    if not ref:
        return None
    if ref.startswith("env:"):
        return os.getenv(ref.removeprefix("env:"))
    return keystore.get(ref)


def embed(config: EmbeddingConfig, api_key: str, texts: list[str]) -> list[list[float]]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": config.model, "input": texts}
    with httpx.Client(timeout=30.0, trust_env=False) as client:
        resp = client.post(f"{config.base_url}/embeddings", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return [item["embedding"] for item in data["data"]]


def embed_text(db: Session, text: str) -> tuple[str, list[float]] | None:
    """嵌入单条文本；未配置或失败返回 None。"""
    config = load_config(db)
    if config is None:
        return None
    api_key = resolve_api_key(config.api_key_ref)
    if not api_key:
        return None
    try:
        vector = embed(config, api_key, [text])[0]
    except Exception:
        return None
    return config.model, vector


def embed_and_store(db: Session, memory_id: str, content: str) -> bool:
    """嵌入内容并 upsert 向量；失败返回 False（不阻塞写入）。"""
    result = embed_text(db, content)
    if result is None:
        return False
    model, vector = result
    existing = db.scalars(
        select(MemoryEmbedding).where(
            MemoryEmbedding.memory_id == memory_id, MemoryEmbedding.model == model
        )
    ).first()
    payload = json.dumps(vector)
    if existing is not None:
        existing.vector_json = payload
    else:
        db.add(
            MemoryEmbedding(
                id=str(uuid4()), memory_id=memory_id, model=model, vector_json=payload
            )
        )
    db.flush()
    return True


def load_vectors(db: Session, memory_ids: list[str]) -> dict[str, list[float]]:
    """批量读取记忆向量；无向量或无 id 的条目忽略。"""
    if not memory_ids:
        return {}
    rows = db.scalars(
        select(MemoryEmbedding).where(MemoryEmbedding.memory_id.in_(memory_ids))
    ).all()
    result: dict[str, list[float]] = {}
    for row in rows:
        try:
            vector = json.loads(row.vector_json)
        except json.JSONDecodeError:
            continue
        if isinstance(vector, list):
            result[row.memory_id] = vector
    return result

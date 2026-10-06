"""Pure OneBot v11 event and message conversions."""

from __future__ import annotations

import ipaddress
import json

from zhiyu.channels.messages import (
    AudioPart,
    FilePart,
    ImagePart,
    MentionPart,
    OutboundMessage,
    QuotePart,
    TextPart,
)


def decode_event(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def mentioned_agent(data: dict) -> bool:
    self_id = str(data.get("self_id", ""))
    message = data.get("message")
    if not self_id or not isinstance(message, list):
        return False
    return any(
        isinstance(segment, dict)
        and segment.get("type") == "at"
        and str((segment.get("data") or {}).get("qq", "")) == self_id
        for segment in message
    )


def extract_text(message) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts = []
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "text":
                parts.append(seg.get("data", {}).get("text", ""))
        return "".join(parts)
    return ""


def extract_parts(message) -> list:
    if isinstance(message, str):
        return [TextPart(text=message)] if message else []
    if not isinstance(message, list):
        return []
    parts = []
    for segment in message:
        if not isinstance(segment, dict):
            continue
        segment_type = segment.get("type")
        data = segment.get("data") or {}
        if segment_type == "text" and data.get("text"):
            parts.append(TextPart(text=str(data["text"])))
        elif segment_type == "at" and data.get("qq") is not None:
            parts.append(
                MentionPart(
                    target_id=str(data["qq"]),
                    display_name=data.get("name"),
                )
            )
        elif segment_type == "reply" and data.get("id") is not None:
            parts.append(QuotePart(message_id=str(data["id"])))
        elif segment_type == "image":
            source = data.get("url") or data.get("file")
            if source:
                parts.append(
                    ImagePart(source=str(source), mime_type=data.get("mime_type"))
                )
        elif segment_type == "record":
            source = data.get("url") or data.get("file")
            if source:
                parts.append(
                    AudioPart(source=str(source), mime_type=data.get("mime_type"))
                )
        elif segment_type == "file":
            source = data.get("url") or data.get("file")
            if source:
                parts.append(
                    FilePart(
                        source=str(source),
                        name=data.get("name"),
                        mime_type=data.get("mime_type"),
                    )
                )
    return parts


def to_onebot_segments(
    message: OutboundMessage, media_store=None
) -> list[dict]:
    segments: list[dict] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            if part.text:
                segments.append({"type": "text", "data": {"text": part.text}})
        elif isinstance(part, MentionPart):
            segments.append({"type": "at", "data": {"qq": part.target_id}})
        elif isinstance(part, QuotePart):
            segments.append({"type": "reply", "data": {"id": part.message_id}})
        elif isinstance(part, ImagePart):
            source = media_store.onebot_source(part.source) if media_store else part.source
            segments.append({"type": "image", "data": {"file": source}})
        elif isinstance(part, AudioPart):
            source = media_store.onebot_source(part.source) if media_store else part.source
            segments.append({"type": "record", "data": {"file": source}})
        elif isinstance(part, FilePart):
            source = media_store.onebot_source(part.source) if media_store else part.source
            data = {"file": source}
            if part.name:
                data["name"] = part.name
            segments.append({"type": "file", "data": data})
    return segments or [{"type": "text", "data": {"text": message.plain_text()}}]


def split_message(
    message: OutboundMessage, limit: int = 4000
) -> list[OutboundMessage]:
    if len(message.parts) != 1 or not isinstance(message.parts[0], TextPart):
        return [message]
    text = message.parts[0].text
    if len(text) <= limit:
        return [message]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = max(
            remaining.rfind("\n", 0, limit + 1),
            remaining.rfind("。", 0, limit + 1),
            remaining.rfind("！", 0, limit + 1),
            remaining.rfind("？", 0, limit + 1),
        )
        cut = cut + 1 if cut >= limit // 2 else limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    return [
        OutboundMessage.text(
            message.conversation_id,
            chunk,
            conversation_type=message.conversation_type,
            source_event_id=message.source_event_id,
        )
        for chunk in chunks
    ]


def is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

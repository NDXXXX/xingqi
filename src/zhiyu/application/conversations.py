"""Conversation history and run queries shared by local entry points."""

import json

from zhiyu.core.agent.run_manager import active_runs
from zhiyu.core.recall import last_local_conversation, list_goals
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.agent_run_repository import AgentRunRepository
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository


def _step_value(value: str | None):
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


class ConversationService:
    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or SessionLocal
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()
        self.runs = AgentRunRepository()
        self.identities = IdentityRepository()

    def list_conversations(self, query: str | None = None, *, character_id: str | None = None, scoped: bool = False) -> list[dict]:
        with self.session_factory() as db:
            return [
                {
                    "id": item.id,
                    "title": item.title,
                    "channel": item.channel,
                    "character_id": item.character_id,
                    "model_id": item.model_id,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                }
                for item in self.conversations.list(db, query)
                if not scoped or item.character_id == character_id
            ]

    def history(self, conversation_id: str) -> list[dict] | None:
        with self.session_factory() as db:
            if self.conversations.get(db, conversation_id) is None:
                return None
            return [
                {
                    "id": item.id,
                    "role": item.role,
                    "content": item.content,
                    "created_at": item.created_at,
                }
                for item in self.messages.list_by_conversation(db, conversation_id)
            ]

    def delete_conversation(self, conversation_id: str) -> bool:
        self.cancel_conversation_run(conversation_id)
        with self.session_factory() as db:
            return self.conversations.delete(db, conversation_id)

    def run_detail(self, run_id: str) -> dict | None:
        with self.session_factory() as db:
            run = self.runs.get(db, run_id)
            if run is None:
                return None
            return {
                "id": run.id,
                "conversation_id": run.conversation_id,
                "provider_id": run.provider_id,
                "model_id": run.model_id,
                "status": run.status,
                "duration_ms": run.duration_ms,
                "prompt_tokens": run.prompt_tokens,
                "completion_tokens": run.completion_tokens,
                "error": run.error,
                "steps": [
                    {
                        "id": step.id,
                        "type": step.step_type,
                        "name": step.name,
                        "status": step.status,
                        "input": _step_value(step.input_json),
                        "output": _step_value(step.output_json),
                        "error": step.error,
                    }
                    for step in run.steps
                ],
            }

    def cancel_run(self, run_id: str) -> bool:
        return active_runs.cancel(run_id)

    def cancel_conversation_run(self, conversation_id: str) -> bool:
        return active_runs.cancel_conversation(conversation_id)

    def local_entry_state(self, conversation_id: str | None) -> tuple[str | None, str | None, list[str]]:
        title = None
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            if conversation_id is None:
                last = last_local_conversation(db, identity_id)
                if last is not None:
                    conversation_id = last.id
                    title = last.title
            goals = list_goals(db, identity_id)
        return conversation_id, title, goals

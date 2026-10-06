"""会话上下文摘要派生数据仓储。"""

from sqlalchemy.orm import Session

from ..models import ConversationSummary, utcnow


class ConversationSummaryRepository:
    def get(self, db: Session, conversation_id: str) -> ConversationSummary | None:
        return db.get(ConversationSummary, conversation_id)

    def upsert(
        self,
        db: Session,
        conversation_id: str,
        content: str,
        source_message_count: int,
        last_message_id: str | None = None,
        last_message_created_at=None,
    ) -> ConversationSummary:
        summary = self.get(db, conversation_id)
        if summary is None:
            summary = ConversationSummary(
                conversation_id=conversation_id,
                content=content,
                source_message_count=source_message_count,
                last_message_id=last_message_id,
                last_message_created_at=last_message_created_at,
            )
            db.add(summary)
        else:
            summary.content = content
            summary.source_message_count = source_message_count
            summary.last_message_id = last_message_id
            summary.last_message_created_at = last_message_created_at
            summary.updated_at = utcnow()
        db.flush()
        return summary

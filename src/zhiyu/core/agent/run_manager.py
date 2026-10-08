"""正在执行的 Agent Run 注册与取消。"""

import asyncio


class ActiveRunManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._conversations: dict[str, str] = {}
        self._channel_sessions: dict[str, tuple[str, str | None, str | None, str]] = {}

    def register(
        self,
        run_id: str,
        conversation_id: str | None = None,
        channel_session: tuple[str, str | None, str | None, str] | None = None,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks[run_id] = task
            if conversation_id is not None:
                self._conversations[run_id] = conversation_id
            if channel_session is not None:
                self._channel_sessions[run_id] = channel_session

    def unregister(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        self._conversations.pop(run_id, None)
        self._channel_sessions.pop(run_id, None)

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def cancel_conversation(self, conversation_id: str) -> bool:
        run_id = next(
            (
                active_id
                for active_id, active_conversation in self._conversations.items()
                if active_conversation == conversation_id
                and active_id in self._tasks
                and not self._tasks[active_id].done()
            ),
            None,
        )
        return self.cancel(run_id) if run_id is not None else False

    def cancel_channel_session(
        self,
        channel: str,
        channel_config_id: str | None,
        conversation_type: str | None,
        external_conversation_id: str,
    ) -> bool:
        target = (channel, channel_config_id, conversation_type, external_conversation_id)
        run_id = next(
            (
                active_id
                for active_id, active_session in self._channel_sessions.items()
                if active_session == target
                and active_id in self._tasks
                and not self._tasks[active_id].done()
            ),
            None,
        )
        return self.cancel(run_id) if run_id is not None else False


active_runs = ActiveRunManager()

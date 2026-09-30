"""正在执行的 Agent Run 注册与取消。"""

import asyncio


class ActiveRunManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def register(self, run_id: str) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks[run_id] = task

    def unregister(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True


active_runs = ActiveRunManager()

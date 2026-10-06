"""渠道入站事件的固定顺序线性流水线。"""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .messages import DeliveryReceipt, InboundEvent, OutboundMessage


class StageDecision(str, Enum):
    CONTINUE = "continue"
    RESPOND = "respond"
    STOP = "stop"


@dataclass(slots=True)
class InboundContext:
    event: InboundEvent
    response_text: str | None = None
    outbound: OutboundMessage | None = None
    delivery: DeliveryReceipt | None = None
    responded: bool = False
    data: dict = field(default_factory=dict)


class InboundStage(Protocol):
    async def process(self, context: InboundContext) -> StageDecision: ...


class InboundPipeline:
    def __init__(self, stages: Iterable[InboundStage]) -> None:
        self.stages = list(stages)

    async def execute(self, event: InboundEvent) -> InboundContext:
        context = InboundContext(event=event)
        for stage in self.stages:
            decision = await stage.process(context)
            if decision is StageDecision.STOP:
                break
            if decision is StageDecision.RESPOND:
                context.responded = True
        return context


class PolicyStage:
    def __init__(self, allowed: Callable[[InboundEvent], bool | Awaitable[bool]]) -> None:
        self.allowed = allowed

    async def process(self, context: InboundContext) -> StageDecision:
        result = self.allowed(context.event)
        if hasattr(result, "__await__"):
            result = await result
        return StageDecision.CONTINUE if result else StageDecision.STOP


class DedupStage:
    """在进入 Agent 前执行可注入的持久化重复检查。"""

    def __init__(
        self,
        is_duplicate: Callable[[InboundEvent], bool | Awaitable[bool]] | None = None,
    ) -> None:
        self.is_duplicate = is_duplicate

    async def process(self, context: InboundContext) -> StageDecision:
        if self.is_duplicate is None:
            return StageDecision.CONTINUE
        result = self.is_duplicate(context.event)
        if hasattr(result, "__await__"):
            result = await result
        context.data["dedup_checked"] = True
        context.data["duplicate"] = bool(result)
        return StageDecision.STOP if result else StageDecision.CONTINUE


class SessionStage:
    """会话解析的显式流水线边界；账号级会话键由 Router 持久化。"""

    async def process(self, context: InboundContext) -> StageDecision:
        return StageDecision.CONTINUE


class NormalizeStage:
    def __init__(
        self,
        normalize: Callable[[InboundEvent], InboundEvent | Awaitable[InboundEvent]],
    ) -> None:
        self.normalize = normalize

    async def process(self, context: InboundContext) -> StageDecision:
        result = self.normalize(context.event)
        if hasattr(result, "__await__"):
            result = await result
        context.event = result
        return StageDecision.CONTINUE


class CommandStage:
    def __init__(
        self,
        commands: dict[str, Callable[[InboundEvent], Awaitable[str]]],
    ) -> None:
        self.commands = commands

    async def process(self, context: InboundContext) -> StageDecision:
        handler = self.commands.get(context.event.text.strip())
        if handler is None:
            return StageDecision.CONTINUE
        context.response_text = await handler(context.event)
        return StageDecision.RESPOND


class AgentStage:
    def __init__(self, handler: Callable[[InboundEvent], Awaitable[str]]) -> None:
        self.handler = handler

    async def process(self, context: InboundContext) -> StageDecision:
        if context.responded:
            return StageDecision.CONTINUE
        context.response_text = await self.handler(context.event)
        return StageDecision.CONTINUE


class RenderStage:
    async def process(self, context: InboundContext) -> StageDecision:
        if context.response_text is not None:
            context.outbound = OutboundMessage.text(
                context.event.conversation_id,
                context.response_text,
                conversation_type=context.event.conversation_type,
                source_event_id=context.event.event_id,
            )
        return StageDecision.CONTINUE


class PersistResponseStage:
    def __init__(self, persist: Callable[[InboundEvent, OutboundMessage], None]) -> None:
        self.persist = persist

    async def process(self, context: InboundContext) -> StageDecision:
        if context.outbound is not None:
            self.persist(context.event, context.outbound)
        return StageDecision.CONTINUE


class DeliveryStage:
    def __init__(
        self,
        sender: Callable[[OutboundMessage], Awaitable[DeliveryReceipt]],
    ) -> None:
        self.sender = sender

    async def process(self, context: InboundContext) -> StageDecision:
        if context.outbound is not None:
            context.delivery = await self.sender(context.outbound)
        return StageDecision.CONTINUE

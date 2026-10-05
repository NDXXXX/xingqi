from unittest.mock import AsyncMock

from zhiyu.channels.messages import DeliveryReceipt, InboundEvent, TextPart
from zhiyu.channels.pipeline import (
    AgentStage,
    CommandStage,
    DeliveryStage,
    InboundPipeline,
    PolicyStage,
    RenderStage,
    StageDecision,
)


def event(text: str = "你好") -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="qq-onebot-default",
        conversation_id="123",
        conversation_type="private",
        sender_id="123",
        parts=[TextPart(text=text)],
    )


async def test_command_response_skips_agent_and_is_delivered():
    command = AsyncMock(return_value="已开启新的对话。")
    agent = AsyncMock(return_value="不应调用")
    sender = AsyncMock(return_value=DeliveryReceipt(status="sent"))
    pipeline = InboundPipeline(
        [
            CommandStage({"/new": command}),
            AgentStage(agent),
            RenderStage(),
            DeliveryStage(sender),
        ]
    )

    result = await pipeline.execute(event("/new"))

    command.assert_awaited_once()
    agent.assert_not_awaited()
    sender.assert_awaited_once()
    assert result.responded is True
    assert result.outbound is not None
    assert result.outbound.plain_text() == "已开启新的对话。"
    assert result.delivery is not None
    assert result.delivery.status == "sent"


async def test_policy_stop_prevents_later_stages():
    agent = AsyncMock(return_value="不应调用")
    sender = AsyncMock(return_value=DeliveryReceipt(status="sent"))
    pipeline = InboundPipeline(
        [
            PolicyStage(lambda _: False),
            AgentStage(agent),
            RenderStage(),
            DeliveryStage(sender),
        ]
    )

    result = await pipeline.execute(event())

    agent.assert_not_awaited()
    sender.assert_not_awaited()
    assert result.response_text is None


async def test_pipeline_preserves_declared_stage_order():
    calls: list[str] = []

    class RecordingStage:
        def __init__(self, name: str, decision: StageDecision) -> None:
            self.name = name
            self.decision = decision

        async def process(self, _context):
            calls.append(self.name)
            return self.decision

    pipeline = InboundPipeline(
        [
            RecordingStage("first", StageDecision.CONTINUE),
            RecordingStage("second", StageDecision.STOP),
            RecordingStage("third", StageDecision.CONTINUE),
        ]
    )

    await pipeline.execute(event())

    assert calls == ["first", "second"]

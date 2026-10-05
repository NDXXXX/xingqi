from unittest.mock import AsyncMock, Mock

from zhiyu.application.runtime import RuntimeHost


async def test_runtime_host_starts_and_stops_owned_services():
    memory_processor = Mock()
    memory_processor.kick = Mock()
    memory_processor.stop = AsyncMock()
    memory_processor.status.return_value = {"pending": 0}
    chat_service = Mock(memory_processor=memory_processor, session_factory=Mock())
    channel_manager = Mock()
    channel_manager.close_all = AsyncMock()
    channel_manager.list.return_value = [{"channel": "qq", "status": "disconnected"}]
    mcp_manager = Mock()
    mcp_manager.close_all = AsyncMock()
    mcp_manager.servers.return_value = []
    skills = Mock()
    host = RuntimeHost(
        chat_service=chat_service,
        channel_manager=channel_manager,
        mcp_manager=mcp_manager,
        skill_registry=skills,
        auto_connect_mcp=False,
    )

    await host.start()
    await host.start()

    skills.reload.assert_called_once()
    memory_processor.kick.assert_called_once()
    assert host.health() == {
        "started": True,
        "channels": [{"channel": "qq", "status": "disconnected"}],
        "mcp_servers": [],
        "memory_jobs": {"pending": 0},
    }

    await host.stop()
    await host.stop()

    channel_manager.close_all.assert_awaited_once()
    mcp_manager.close_all.assert_awaited_once()
    memory_processor.stop.assert_awaited_once()
    assert host.started is False


async def test_runtime_host_context_manager_always_stops():
    memory_processor = Mock(
        kick=Mock(),
        stop=AsyncMock(),
        status=Mock(return_value={}),
    )
    chat_service = Mock(memory_processor=memory_processor, session_factory=Mock())
    channel_manager = Mock(close_all=AsyncMock(), list=Mock(return_value=[]))
    mcp_manager = Mock(close_all=AsyncMock(), servers=Mock(return_value=[]))
    skills = Mock(reload=Mock())
    host = RuntimeHost(
        chat_service=chat_service,
        channel_manager=channel_manager,
        mcp_manager=mcp_manager,
        skill_registry=skills,
        auto_connect_mcp=False,
    )

    async with host:
        assert host.started is True

    assert host.started is False
    channel_manager.close_all.assert_awaited_once()

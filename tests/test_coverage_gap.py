"""Quick coverage tests for main entry point and health checker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMainEntryPoint:
    def test_main_imports(self) -> None:
        """Verify the main module imports without side effects."""
        import vpn.__main__
        assert hasattr(vpn.__main__, "main")

    def test_main_function_exists(self) -> None:
        """Verify main() is callable."""
        from vpn.__main__ import main
        assert callable(main)


class TestHealthChecker:
    @pytest.mark.asyncio
    async def test_run_forever_posts_events(self) -> None:
        """Verify health checker posts HEALTH_OK events to queue."""
        import asyncio
        from unittest.mock import MagicMock

        from vpn.core.events import EventType
        from vpn.core.health.checker import HealthChecker

        mock_shell = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_shell.run.return_value = mock_result

        checker = HealthChecker(
            shell=mock_shell,
            targets=["https://example.com"],
            user_agents=["TestAgent/1.0"],
            interval_range=(1, 2),
            sample_size=1,
        )

        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(checker.run_forever(queue))

        # Wait for first event
        try:
            event = await asyncio.wait_for(queue.get(), timeout=5)
            assert event.type == EventType.HEALTH_OK
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def test_check_returns_false_when_all_fail(self) -> None:
        """Verify _check returns False when all targets unreachable."""
        from unittest.mock import MagicMock

        from vpn.core.health.checker import HealthChecker

        mock_shell = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_shell.run.return_value = mock_result

        checker = HealthChecker(
            shell=mock_shell,
            targets=["https://bad.example.com"],
            user_agents=["TestAgent/1.0"],
            interval_range=(1, 2),
            sample_size=1,
        )

        result = checker._check()
        assert result is False


class TestTun2Socks:
    def test_is_alive_when_no_handle(self) -> None:
        from unittest.mock import MagicMock
        from vpn.core.tunnel.tun2socks import Tun2SocksManager
        mgr = Tun2SocksManager(MagicMock())
        assert mgr.is_alive is False

    def test_start_returns_handle(self) -> None:
        from unittest.mock import MagicMock
        from vpn.core.tunnel.tun2socks import Tun2SocksManager
        mock_subproc = MagicMock()
        mock_handle = MagicMock(pid=1234)
        mock_handle.poll.return_value = None
        mock_subproc.popen.return_value = mock_handle
        mgr = Tun2SocksManager(mock_subproc)
        handle = mgr.start("socks5://127.0.0.1:3066")
        assert handle is not None

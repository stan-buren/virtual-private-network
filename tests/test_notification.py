"""Tests for Telegram notification — formatting, IPv4 patch, retry logic."""

from __future__ import annotations

import os
import socket
import time
from unittest.mock import Mock, patch

from vpn.core.notification.telegram import TelegramNotifier


class TestTelegramNotifierFormatting:
    def test_format_event_substitutes_values(self) -> None:
        notifier = TelegramNotifier(token="fake", chat_id="123")
        result = notifier.format_event(
            "Server {name} in {country}", name="barguzin", country="ru"
        )
        assert result == "Server barguzin in ru"

    def test_format_event_handles_multiple_placeholders(self) -> None:
        notifier = TelegramNotifier(token="fake", chat_id="123")
        result = notifier.format_event(
            "{action} {target} at {timestamp}",
            action="SWITCHED", target="barguzin", timestamp="2026-07-25T12:00:00Z",
        )
        assert result == "SWITCHED barguzin at 2026-07-25T12:00:00Z"

    def test_format_event_raises_on_missing_key(self) -> None:
        import pytest
        notifier = TelegramNotifier(token="fake", chat_id="123")
        with pytest.raises(KeyError):
            notifier.format_event("Hello {missing}", name="barguzin")


class TestTelegramNotifierTokenResolution:
    def test_token_from_env(self) -> None:
        with patch.dict(os.environ, {
            "VPN_TELEGRAM_TOKEN": "env_token",
            "VPN_TELEGRAM_CHAT_ID": "env_chat",
        }):
            notifier = TelegramNotifier()
            assert notifier._token == "env_token"
            assert notifier._chat_id == "env_chat"

    def test_custom_token_overrides_env(self) -> None:
        with patch.dict(os.environ, {
            "VPN_TELEGRAM_TOKEN": "env_token",
            "VPN_TELEGRAM_CHAT_ID": "env_chat",
        }):
            notifier = TelegramNotifier(token="custom", chat_id="456")
            assert notifier._token == "custom"
            assert notifier._chat_id == "456"

    def test_token_defaults_to_empty_string(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            notifier = TelegramNotifier()
            assert notifier._token == ""
            assert notifier._chat_id == ""

    def test_api_url_includes_token(self) -> None:
        notifier = TelegramNotifier(token="my_token_value", chat_id="123")
        assert "my_token_value" in notifier._api_url
        assert notifier._api_url.startswith("https://api.telegram.org/bot")


class TestTelegramNotifierSend:
    def test_send_skips_when_no_token(self) -> None:
        notifier = TelegramNotifier(token="", chat_id="")
        notifier.send("test message")
        # Should not raise

    def test_send_skips_when_no_chat_id(self) -> None:
        notifier = TelegramNotifier(token="fake", chat_id="")
        notifier.send("test message")
        # Should not raise

    def test_send_skips_when_both_empty(self) -> None:
        notifier = TelegramNotifier(token="", chat_id="")
        notifier.send("test message")
        # Should not raise

    @patch("urllib.request.urlopen")
    def test_send_patches_socket_to_ipv4_only(self, mock_urlopen: Mock) -> None:
        """Verify socket.getaddrinfo is temporarily replaced during send."""
        orig_getaddrinfo = socket.getaddrinfo
        captured_during_call: object = None

        def capture_state(*args: object, **kwargs: object) -> None:
            nonlocal captured_during_call
            captured_during_call = socket.getaddrinfo

        mock_urlopen.side_effect = capture_state

        notifier = TelegramNotifier(token="fake", chat_id="123")
        notifier.send("test message", retries=1)

        assert captured_during_call is not None, "urlopen was never called"
        assert captured_during_call is not orig_getaddrinfo, (
            "socket.getaddrinfo was not replaced during send"
        )
        assert socket.getaddrinfo is orig_getaddrinfo, (
            "socket.getaddrinfo was not restored after send"
        )

    @patch("urllib.request.urlopen")
    def test_send_restores_socket_getaddrinfo_after_success(self, mock_urlopen: Mock) -> None:
        orig = socket.getaddrinfo
        notifier = TelegramNotifier(token="fake", chat_id="123")
        notifier.send("test message", retries=1)
        assert socket.getaddrinfo is orig

    @patch("urllib.request.urlopen")
    def test_send_restores_socket_getaddrinfo_after_failure(self, mock_urlopen: Mock) -> None:
        mock_urlopen.side_effect = OSError("network down")
        orig = socket.getaddrinfo
        notifier = TelegramNotifier(token="fake", chat_id="123")
        notifier.send("test message", retries=1)
        assert socket.getaddrinfo is orig


class TestTelegramNotifierRetry:
    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_send_retries_on_failure(self, mock_sleep: Mock, mock_urlopen: Mock) -> None:
        mock_urlopen.side_effect = [
            OSError("attempt 1 failed"),
            OSError("attempt 2 failed"),
            None,  # success on 3rd
        ]
        notifier = TelegramNotifier(token="fake", chat_id="123")
        notifier.send("test message", retries=3, retry_delay=2)
        assert mock_urlopen.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_send_stops_after_max_retries(self, mock_sleep: Mock, mock_urlopen: Mock) -> None:
        mock_urlopen.side_effect = OSError("always fails")
        notifier = TelegramNotifier(token="fake", chat_id="123")
        notifier.send("test message", retries=3, retry_delay=1)
        assert mock_urlopen.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("urllib.request.urlopen")
    def test_send_succeeds_first_try_without_sleep(self, mock_urlopen: Mock) -> None:
        notifier = TelegramNotifier(token="fake", chat_id="123")
        with patch("time.sleep") as mock_sleep:
            notifier.send("test message", retries=3)
            mock_sleep.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_send_uses_custom_retry_delay(self, mock_urlopen: Mock) -> None:
        mock_urlopen.side_effect = [OSError("fail"), None]
        notifier = TelegramNotifier(token="fake", chat_id="123")
        with patch("time.sleep") as mock_sleep:
            notifier.send("test message", retries=2, retry_delay=7)
            mock_sleep.assert_called_once_with(7)


class TestTelegramNotifierMessagePrefix:
    @patch("urllib.request.urlopen")
    def test_send_prepends_service_alert_prefix(self, mock_urlopen: Mock) -> None:
        notifier = TelegramNotifier(token="fake", chat_id="123")
        notifier.send("server down", retries=1)

        call_args = mock_urlopen.call_args
        # urlopen(url, data=data, timeout=8)
        data_arg = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("data")
        decoded = data_arg.decode() if isinstance(data_arg, bytes) else data_arg
        assert "Service+Alert+%28Asus+VPN%29%3A+server+down" in decoded
